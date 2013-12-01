#!/usr/bin/python
# -*- coding: utf-8 -*-

###########################################################################

import os
import sys
import time
import datetime
import pycurl
from cStringIO import StringIO
import sqlite3 as lite
import re
import subprocess
import pygal

###########################################################################

IMAGE_WIDTH = 800
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SVG_DIR    = SCRIPT_DIR + '/svg'
DB_FILE    = SCRIPT_DIR + '/db.sqlite'

PING_HOST  = "www.google.com"
PING_COUNT = 3

LIVE_HOURS = 6

ACTION = sys.argv[1] if len(sys.argv) > 1 else False

###########################################################################

def drange(start, stop, step):
	r = start
	while r < stop:
		yield r
		r += step

###########################################################################

# CURL get content
def get_content(url, *args, **kargs):
	c = pycurl.Curl()
	c.setopt(pycurl.URL, url)
	c.bodyio = StringIO()
	c.setopt(pycurl.WRITEFUNCTION, c.bodyio.write)
	c.get_body = c.bodyio.getvalue
	c.headio = StringIO()
	c.setopt(pycurl.HEADERFUNCTION, c.headio.write)
	c.get_head = c.headio.getvalue

	c.setopt(pycurl.FOLLOWLOCATION, 1)
	c.setopt(pycurl.MAXREDIRS, 5)
	c.setopt(pycurl.CONNECTTIMEOUT, 60)
	c.setopt(pycurl.TIMEOUT, 120)
	c.setopt(pycurl.NOSIGNAL, 1)
	c.setopt(pycurl.USERAGENT, 'Mozilla/5.0 (X11; Ubuntu; Linux i686; rv:13.0) Gecko/20100101 Firefox/13.0')
	httpheader = [
		'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
		'Accept-Language: ru-ru,ru;q=0.8,en-us;q=0.5,en;q=0.3',
		'Accept-Charset:utf-8;q=0.7,*;q=0.5',
		'Connection: keep-alive'
	]
	c.setopt(pycurl.HTTPHEADER, httpheader)

	c.perform()
	if c.getinfo(pycurl.HTTP_CODE) != 200:
		raise Exception('HTTP code is %s' % c.getinfo(pycurl.HTTP_CODE))

	return c.get_body()


###########################################################################

def get_yota_stat():
	unixtime = str(int(time.time()))
	try:
		ajax_result = get_content('http://10.0.0.1/cgi-bin/sysconf.cgi?_='+unixtime+'&page=ajax.asp&action=get_status&time='+unixtime)
	except:
		return {}

	yota_info   = {}
	ajax_result = ajax_result.split('\n')
	for row in ajax_result:
		k = row.split('=')
		if k[0]:
			yota_info[k[0]] = k[1] if len(k) > 1 else None

	config = {
		'SINR':           {'key':'3GPP.SINR', 'type':'int'},
		'RSRP':           {'key':'3GPP.RSRP', 'type':'int'},
		'RSSI':           {'key':'3GPP.RSSI', 'type':'int'},
		'RSRQ':           {'key':'3GPP.RSRQ', 'type':'int'},
		'PLMN':           {'key':'3GPP.PLMN', 'type':'int'},
		'MCC':            {'key':'3GPP.MCC', 'type':'int'},
		'conn_time':      {'key':'ConnectedTime', 'type':'int'},
		'received_bytes': {'key':'ReceivedBytes', 'type':'int'},
		'sent_bytes':     {'key':'SentBytes', 'type':'int'},
		'max_up_link':    {'key':'MaxUplinkThroughput', 'type':'int'},
		'max_down_link':  {'key':'MaxDownlinkThroughput', 'type':'int'},
		'state':  {'key':'State', 'type':'bool', 'valid':'Connected'},
	}

	result = {}

	for k in config:
		data_type = config[k]['type']
		data_key  = config[k]['key']
		val       = yota_info[data_key] if data_key in yota_info else None

		if 'int' == data_type:
			val = int(val)
		elif 'bool' == data_type:
			valid_value = config[k]['valid'] if 'valid' in config[k] else True
			val = val == valid_value

		result[k] = val

	return result

###########################################################################

def get_yota_stat_avg(iterations = 5):
	avg_stat = {}
	while iterations > 0:
		stat = get_yota_stat()

		if avg_stat:
			for k in stat:
				avg_stat[k] = (avg_stat[k] + stat[k]) / 2
		else:
			avg_stat = stat

		iterations = iterations - 1
		if iterations:
			time.sleep(1)

	return avg_stat

###########################################################################

def dict_factory(cursor, row):
	d = {}
	for idx, col in enumerate(cursor.description):
		d[col[0]] = row[idx]
	return d

###########################################################################

def db_insert(table, data):
	for k in data:
		if isinstance(data[k], bool):
			data[k] = int(data[k])

	sql = "INSERT INTO "+table+" ("+(", ".join(data.keys()))+") VALUES ("+str(data.values())[1:-1]+")"
	conn.execute(sql)
	conn.commit()

###########################################################################

def ping(host, iterations=1):
	cmd = "/sbin/ping -c " + str(iterations) + " " + host
	p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=open('/dev/null', 'w'))
	out = p.stdout.read()

	if out == '' or out == None or len(out) == 0:
		return False

	try:
		match  = re.search('round-trip min/avg/max/stddev = (\d+\.\d+)/(\d+\.\d+)/(\d+\.\d+)/(\d+\.\d+)', out)
		result = match.groups()
	except:
		return False

	return {
		'min':    float(result[0]),
		'avg':    float(result[1]),
		'max':    float(result[2]),
		'stddev': float(result[3]),
	}

###########################################################################

def svg_save(svg_filename, xml_content):
	svg = open(SVG_DIR + '/' + svg_filename + '.svg', 'w')
	svg.write(xml_content)
	svg.close()

###########################################################################

def make_chart(sql='', type='line', config={}, file=None, keys=None, height=0, range=None, rotate_lable=False, legend=True, y_labels=False, show_y_labels=True, show_x_labels=True, debug = False):
	cur.execute(sql)
	data = {}
	while True:
		row = cur.fetchone()
		if row == None:
			break
		for k in row:
			if k not in data:
				data[k] = []
			val = False if row[k] == None else row[k]
			data[k].append(val)
	if debug:
		print data

	conf                  = pygal.Config()
	conf.width            = IMAGE_WIDTH
	conf.height           = height if height else IMAGE_WIDTH/3
	conf.show_legend      = legend
	conf.show_y_labels    = show_y_labels
	conf.show_x_labels    = show_x_labels
	conf.human_readable   = True
	conf.legend_at_bottom = True
	conf.fill             = True
	conf.spacing          = 10
	conf.margin          = 20
	# conf.style          = pygal.style.DarkSolarizedStyle

	if rotate_lable:
		conf.x_label_rotation = rotate_lable
	if range:
		conf.range = range

	if type == 'Line':
		chart = pygal.Line(conf)
	elif type == 'Dot':
		chart = pygal.Dot(conf)
	elif type == 'Bar':
		chart = pygal.Bar(conf)
	elif type == 'StackedBar':
		chart = pygal.StackedBar(conf)

	chart.x_labels = data['d']

	if y_labels:
		chart.y_labels = y_labels

	if keys == None:
		keys = data.keys()

	for k in keys:
		if k != 'd':
			chart.add(k, data[k])

	svg_save(file, chart.render())

###########################################################################
###########################################################################
###########################################################################

conn = lite.connect(DB_FILE)
conn.row_factory = dict_factory
cur = conn.cursor()

generate_img = ACTION == 'generate-img'

# default action
if ACTION == False:
	# Get and save data
	ping = ping(PING_HOST, PING_COUNT)
	stat = get_yota_stat_avg()

	if ping:
		stat['ping_status'] = True
		stat['ping']        = ping['avg']
	else:
		stat['ping_status'] = False
	db_insert('log', stat)

###########################################################################

if ACTION == False or generate_img:
	now = datetime.datetime.now()

	gen_live = True

	if generate_img:
		gen_day  = True
		gen_week = True
	else:
		# gen every hour *:00 - *:10
		gen_day_time = int(now.strftime("%M"))
		gen_day =  gen_day_time > 0 and gen_day_time < 10

		# gen form 23:50 - 24:00
		gen_week_time = int(now.strftime("%H%M"))
		gen_week = gen_week_time > 2350 and gen_week_time < 2400

	# print 'gen_live: ', gen_live
	# print 'gen_day: ', gen_day
	# print 'gen_week: ', gen_week

	# exit()

	# internet_status
	if gen_live:
		make_chart(
			file         = 'live_internet_status',
			sql          = "SELECT strftime('%H:%M', `date`) d, SUM(ping_status) valid, COUNT(ping_status) - SUM(ping_status) AS errors, 1 - COUNT(ping_status) AS lost  FROM log WHERE `date` > (SELECT DATETIME('now', '-"+str(LIVE_HOURS)+" hour', 'localtime')) GROUP BY d ORDER BY id",
			type         = 'StackedBar',
			height       = 150,
			rotate_lable = 60,
			keys         = ['errors', 'valid', 'lost'],
			show_y_labels     = False,
			legend       = False
		)
	if gen_day:
		make_chart(
			file     = 'day_internet_status',
			sql      = "SELECT strftime('%H', `date`) d, SUM(ping_status) valid, COUNT(ping_status) - SUM(ping_status) AS errors, 12 - COUNT(ping_status) AS lost FROM log WHERE `date` > (SELECT DATETIME('now', '-1 day', 'localtime')) GROUP BY d ORDER BY id",
			type     = 'StackedBar',
			height   = 150,
			show_y_labels = False,
			keys     = ['errors', 'valid', 'lost'],
			legend   = False
		)
	if gen_week:
		make_chart(
			file     = 'week_internet_status',
			sql      = "SELECT strftime('%d.%m', `date`) d, SUM(ping_status) valid, COUNT(ping_status) - SUM(ping_status) AS errors FROM log WHERE `date` > (SELECT DATETIME('now', '-7 day', 'localtime')) GROUP BY d ORDER BY id",
			type     = 'StackedBar',
			height   = 150,
			show_y_labels = False,
			keys     = ['errors', 'valid'],
			legend   = False
		)

	# Ping
	if gen_live:
		make_chart(
			file         = 'live_ping',
			sql          = "SELECT strftime('%H:%M', `date`) d, cast(AVG(ping) as int) ping FROM log WHERE `date` > (SELECT DATETIME('now', '-"+str(LIVE_HOURS)+" hour', 'localtime')) GROUP BY d ORDER BY id",
			type         = 'Bar',
			rotate_lable = 60,
			legend       = False
		)
	if gen_day:
		make_chart(
			file   = 'day_ping',
			sql    = "SELECT strftime('%H', `date`) d, cast(AVG(ping) as int) ping FROM log WHERE `date` > (SELECT DATETIME('now', '-1 day', 'localtime')) GROUP BY d ORDER BY id",
			type   = 'Bar',
			legend = False,
		)
	if gen_week:
		make_chart(
			file   = 'week_ping',
			sql    = "SELECT strftime('%d.%m', `date`) d, cast(AVG(ping) as int) ping FROM log WHERE `date` > (SELECT DATETIME('now', '-7 day', 'localtime')) GROUP BY d ORDER BY id",
			type   = 'Bar',
			legend = False,
		)


	# SINR
	if gen_live:
		make_chart(
			file         = 'live_sinr',
			sql          = "SELECT strftime('%H:%M', `date`) d, AVG(SINR) SINR FROM log WHERE `date` > (SELECT DATETIME('now', '-"+str(LIVE_HOURS)+" hour', 'localtime')) GROUP BY d ORDER BY id",
			type         = 'Bar',
			rotate_lable = 60,
			legend       = False,
		)
	if gen_day:
		make_chart(
			file   = 'day_sinr',
			sql    = "SELECT strftime('%H', `date`) d, AVG(SINR) SINR FROM log WHERE `date` > (SELECT DATETIME('now', '-1 day', 'localtime')) GROUP BY d ORDER BY id",
			type   = 'Bar',
			legend = False,
		)
	if gen_week:
		make_chart(
			file   = 'week_sinr',
			sql    = "SELECT strftime('%d.%m', `date`) d, AVG(SINR) SINR FROM log WHERE `date` > (SELECT DATETIME('now', '-7 day', 'localtime')) GROUP BY d ORDER BY id",
			type   = 'Bar',
			legend = False,
		)


	# RSSI RSRP
	if gen_live:
		make_chart(
			file         = 'live_rssi_rsrp',
			sql          = "SELECT strftime('%H:%M', `date`) d, AVG(RSSI) RSSI, AVG(RSRP) RSRP FROM log WHERE `date` > (SELECT DATETIME('now', '-"+str(LIVE_HOURS)+" hour', 'localtime')) GROUP BY d ORDER BY id",
			type         = 'Line',
			rotate_lable = 60,
			keys         = ['RSRP', 'RSSI'],
		)
	if gen_day:
		make_chart(
			file = 'day_rssi_rsrp',
			sql  = "SELECT strftime('%H', `date`) d, AVG(RSSI) RSSI, AVG(RSRP) RSRP FROM log WHERE `date` > (SELECT DATETIME('now', '-1 day', 'localtime')) GROUP BY d ORDER BY id",
			type = 'Line',
			# range = (-100, -50),
			# y_labels = drange(-100, -50, 5),
			keys = ['RSRP', 'RSSI'],
		)
	if gen_week:
		make_chart(
			file   = 'week_rssi_rsrp',
			sql    = "SELECT strftime('%d.%m', `date`) d, AVG(RSSI) RSSI, AVG(RSRP) RSRP FROM log WHERE `date` > (SELECT DATETIME('now', '-7 day', 'localtime')) GROUP BY d ORDER BY id",
			type   = 'Bar',
			keys = ['RSRP', 'RSSI'],
		)

###########################################################################

if ACTION == 'debug':
	print 'debug'
	make_chart(
		debug        = True,
		file         = 'live_rssi_rsrp',
		sql          = "SELECT strftime('%H:%M', `date`) d, AVG(RSSI) RSSI, AVG(RSRP) RSRP FROM log WHERE `date` > (SELECT DATETIME('now', '-"+str(LIVE_HOURS)+" hour', 'localtime')) GROUP BY d ORDER BY id",
		type         = 'Line',
		rotate_lable = 60,
		keys         = ['RSRP', 'RSSI'],
	)

###########################################################################

conn.close()

###########################################################################
