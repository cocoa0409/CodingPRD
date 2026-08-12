from datetime import timedelta

from flask import Blueprint, request

import db
from errors import ApiError, invalid
from middleware import auth
from response import ok, ok_list
from util import body, require, as_str, as_bool, find, serialize, parse_dt

bp = Blueprint('delivery', __name__)

DT_FIELDS = ('window_start', 'window_end')
TRAVEL_BUFFER = timedelta(minutes=30)


def ser_job(job):
    return serialize(job, DT_FIELDS)


def _not_actionable(message='delivery job is not in the required state'):
    return ApiError('ERR_DELIVERY_NOT_ACTIONABLE', 409, message)


def _validate_window(d):
    start = parse_dt(require(d, 'window_start'), 'window_start')
    end = parse_dt(require(d, 'window_end'), 'window_end')
    if end <= start:
        raise invalid('window_end must be strictly after window_start')
    return start, end


def _climate_check(order, crew):
    if order['climate_controlled_required'] and not crew['climate_certified']:
        raise ApiError('ERR_CLIMATE_REQUIREMENT_UNMET', 422,
                       'order requires a climate-certified crew')


def _overlap_check(crew_id, start, end, exclude_id=None):
    """Half-open overlap with a mandatory 30-minute post-job travel buffer."""
    for job in db.stores['jobs'].values():
        if job['crew_id'] != crew_id or job['id'] == exclude_id:
            continue
        if job['status'] not in ('SCHEDULED', 'EN_ROUTE'):
            continue
        buffered_end = job['window_end'] + TRAVEL_BUFFER
        if start < buffered_end and job['window_start'] < end:
            raise ApiError('ERR_CREW_WINDOW_CONFLICT', 409,
                           'window conflicts with another job of this crew')


@bp.post('/piano-dealer/delivery-crews')
def create_crew():
    auth('StoreManager')
    d = body()
    rec = db.base_fields()
    rec.update({
        'crew_name': as_str(require(d, 'crew_name'), 'crew_name'),
        'climate_certified': as_bool(require(d, 'climate_certified'), 'climate_certified'),
    })
    db.stores['crews'][rec['id']] = rec
    return ok(serialize(rec), 201)


@bp.post('/piano-dealer/delivery-jobs')
def create_job():
    auth('ServiceCoordinator')
    d = body()
    order_id = as_str(require(d, 'order_id'), 'order_id')
    crew_id = as_str(require(d, 'crew_id'), 'crew_id')
    start, end = _validate_window(d)
    order = find(db.stores['orders'], order_id, 'order')
    crew = find(db.stores['crews'], crew_id, 'crew')
    if order['fulfillment_status'] != 'AWAITING_SCHEDULING' \
            or order['payment_status'] not in ('DEPOSIT_PAID', 'PAID_IN_FULL', 'FINANCED_ACTIVE'):
        raise _not_actionable('order is not in a schedulable state')
    _climate_check(order, crew)
    _overlap_check(crew_id, start, end)
    rec = db.base_fields()
    rec.update({
        'order_id': order_id,
        'crew_id': crew_id,
        'window_start': start,
        'window_end': end,
        'status': 'SCHEDULED',
    })
    db.stores['jobs'][rec['id']] = rec
    order['fulfillment_status'] = 'DELIVERY_SCHEDULED'
    db.touch(order)
    return ok(ser_job(rec), 201)


@bp.get('/piano-dealer/delivery-jobs/<rid>')
def get_job(rid):
    auth('ServiceCoordinator')
    return ok(ser_job(find(db.stores['jobs'], rid, 'delivery job')))


@bp.get('/piano-dealer/delivery-jobs')
def list_jobs():
    auth('ServiceCoordinator', 'StoreManager')
    items = list(db.stores['jobs'].values())
    order_id = request.args.get('order_id')
    crew_id = request.args.get('crew_id')
    if order_id:
        items = [j for j in items if j['order_id'] == order_id]
    if crew_id:
        items = [j for j in items if j['crew_id'] == crew_id]
    return ok_list(items, ser_job)


@bp.post('/piano-dealer/delivery-jobs/<rid>/start')
def start_job(rid):
    auth('ServiceCoordinator')
    job = find(db.stores['jobs'], rid, 'delivery job')
    if job['status'] != 'SCHEDULED':
        raise _not_actionable('only SCHEDULED jobs can be started')
    job['status'] = 'EN_ROUTE'
    db.touch(job)
    order = find(db.stores['orders'], job['order_id'], 'order')
    order['fulfillment_status'] = 'OUT_FOR_DELIVERY'
    db.touch(order)
    return ok(ser_job(job))


@bp.post('/piano-dealer/delivery-jobs/<rid>/complete')
def complete_job(rid):
    auth('ServiceCoordinator')
    job = find(db.stores['jobs'], rid, 'delivery job')
    if job['status'] != 'EN_ROUTE':
        raise _not_actionable('only EN_ROUTE jobs can be completed')
    job['status'] = 'COMPLETED'
    db.touch(job)
    order = find(db.stores['orders'], job['order_id'], 'order')
    order['fulfillment_status'] = 'DELIVERED'
    order['delivered_at'] = db.now()
    db.touch(order)
    for item in order['items']:
        inst = find(db.stores['instruments'], item['instrument_id'], 'instrument')
        if inst['status'] == 'SOLD':
            inst['status'] = 'DELIVERED'
            db.touch(inst)
    return ok(ser_job(job))


@bp.post('/piano-dealer/delivery-jobs/<rid>/fail')
def fail_job(rid):
    auth('ServiceCoordinator')
    job = find(db.stores['jobs'], rid, 'delivery job')
    if job['status'] != 'EN_ROUTE':
        raise _not_actionable('only EN_ROUTE jobs can be failed')
    job['status'] = 'FAILED'
    db.touch(job)
    order = find(db.stores['orders'], job['order_id'], 'order')
    order['fulfillment_status'] = 'DELIVERY_SCHEDULED'
    db.touch(order)
    return ok(ser_job(job))


@bp.post('/piano-dealer/delivery-jobs/<rid>/reschedule')
def reschedule_job(rid):
    auth('ServiceCoordinator')
    job = find(db.stores['jobs'], rid, 'delivery job')
    d = body()
    start, end = _validate_window(d)
    if job['status'] != 'FAILED':
        raise _not_actionable('only FAILED jobs can be rescheduled')
    order = find(db.stores['orders'], job['order_id'], 'order')
    crew = find(db.stores['crews'], job['crew_id'], 'crew')
    _climate_check(order, crew)
    _overlap_check(job['crew_id'], start, end, exclude_id=job['id'])
    job['window_start'] = start
    job['window_end'] = end
    job['status'] = 'SCHEDULED'
    db.touch(job)
    return ok(ser_job(job))
