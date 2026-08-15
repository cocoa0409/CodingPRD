from flask import Blueprint, request

import calc
import db
from errors import ApiError, invalid, forbidden
from middleware import auth
from response import ok, ok_list
from util import body, require, as_str, as_enum, find, serialize, parse_dt

bp = Blueprint('services', __name__)

DT_FIELDS = ('window_start', 'window_end')
TIERS = ('BASIC', 'STANDARD', 'PREMIUM')
MAX_TECH_VISITS_PER_DAY = 4


def ser_visit(visit):
    return serialize(visit, DT_FIELDS)


def _plan_not_active(message='service plan is not in the required state'):
    return ApiError('ERR_PLAN_NOT_ACTIVE', 409, message)


def _recompute_available(plan):
    plan['visits_available'] = plan['visits_total'] - plan['visits_used'] - plan['visits_booked']


def _auto_exhaust(plan):
    """On every plan mutation: EXHAUSTED when all visits used and none booked."""
    if plan['status'] == 'ACTIVE' \
            and plan['visits_used'] == plan['visits_total'] and plan['visits_booked'] == 0:
        plan['status'] = 'EXHAUSTED'
        db.touch(plan)


@bp.post('/piano-dealer/technicians')
def create_technician():
    auth('StoreManager')
    d = body()
    rec = db.base_fields()
    rec.update({
        'full_name': as_str(require(d, 'full_name'), 'full_name'),
        'certification_level': as_enum(require(d, 'certification_level'), 'certification_level',
                                       ('STANDARD', 'MASTER')),
    })
    db.stores['technicians'][rec['id']] = rec
    return ok(serialize(rec), 201)


@bp.post('/piano-dealer/service-plans')
def create_plan():
    auth('ServiceCoordinator')
    d = body()
    order_id = as_str(require(d, 'order_id'), 'order_id')
    tier = as_enum(require(d, 'tier'), 'tier', TIERS)
    order = find(db.stores['orders'], order_id, 'order')
    if order['fulfillment_status'] != 'INSTALLED':
        raise ApiError('ERR_DELIVERY_NOT_ACTIONABLE', 409,
                       'service plans require an INSTALLED order')
    visits_total = calc.TIER_VISITS[tier]
    rec = db.base_fields()
    rec.update({
        'order_id': order_id,
        'tier': tier,
        'price_cents': calc.plan_price(tier, order['customer_id']),
        'visits_total': visits_total,
        'visits_used': 0,
        'visits_booked': 0,
        'visits_available': visits_total,
        'status': 'ACTIVE',
    })
    db.stores['plans'][rec['id']] = rec
    return ok(serialize(rec), 201)


@bp.get('/piano-dealer/service-plans/<rid>')
def get_plan(rid):
    uid, role = auth('ServiceCoordinator', 'Customer')
    plan = find(db.stores['plans'], rid, 'service plan')
    if role == 'Customer':
        order = find(db.stores['orders'], plan['order_id'], 'order')
        if order['customer_id'] != uid:
            raise forbidden('customer may only read their own service plans')
    return ok(serialize(plan))


@bp.get('/piano-dealer/service-plans')
def list_plans():
    auth('ServiceCoordinator')
    items = list(db.stores['plans'].values())
    order_id = request.args.get('order_id')
    if order_id:
        items = [p for p in items if p['order_id'] == order_id]
    return ok_list(items, serialize)


@bp.post('/piano-dealer/service-plans/<rid>/suspend')
def suspend_plan(rid):
    auth('ServiceCoordinator')
    plan = find(db.stores['plans'], rid, 'service plan')
    if plan['status'] != 'ACTIVE':
        raise _plan_not_active('only ACTIVE plans can be suspended')
    plan['status'] = 'SUSPENDED'
    db.touch(plan)
    return ok(serialize(plan))


@bp.post('/piano-dealer/service-plans/<rid>/resume')
def resume_plan(rid):
    auth('ServiceCoordinator')
    plan = find(db.stores['plans'], rid, 'service plan')
    if plan['status'] != 'SUSPENDED':
        raise _plan_not_active('only SUSPENDED plans can be resumed')
    plan['status'] = 'ACTIVE'
    db.touch(plan)
    _auto_exhaust(plan)
    return ok(serialize(plan))


@bp.post('/piano-dealer/service-plans/<rid>/cancel')
def cancel_plan(rid):
    auth('ServiceCoordinator')
    plan = find(db.stores['plans'], rid, 'service plan')
    if plan['status'] not in ('ACTIVE', 'SUSPENDED'):
        raise _plan_not_active('only ACTIVE or SUSPENDED plans can be cancelled')
    plan['status'] = 'CANCELLED'
    for visit in db.stores['visits'].values():
        if visit['plan_id'] == plan['id'] and visit['status'] == 'BOOKED':
            visit['status'] = 'CANCELLED'
            db.touch(visit)
    plan['visits_booked'] = 0
    _recompute_available(plan)
    db.touch(plan)
    return ok(serialize(plan))


@bp.post('/piano-dealer/service-visits')
def create_visit():
    auth('ServiceCoordinator')
    d = body()
    plan_id = as_str(require(d, 'plan_id'), 'plan_id')
    technician_id = as_str(require(d, 'technician_id'), 'technician_id')
    start = parse_dt(require(d, 'window_start'), 'window_start')
    end = parse_dt(require(d, 'window_end'), 'window_end')
    if end <= start:
        raise invalid('window_end must be strictly after window_start')
    plan = find(db.stores['plans'], plan_id, 'service plan')
    find(db.stores['technicians'], technician_id, 'technician')
    if plan['status'] != 'ACTIVE':
        raise _plan_not_active('visits can only be booked on an ACTIVE plan')
    # Technician closed-interval overlap: shared endpoints conflict.
    booked = [v for v in db.stores['visits'].values()
              if v['technician_id'] == technician_id and v['status'] == 'BOOKED']
    for v in booked:
        if start <= v['window_end'] and v['window_start'] <= end:
            raise ApiError('ERR_TECHNICIAN_WINDOW_CONFLICT', 409,
                           'visit conflicts with another booked visit of this technician')
    # Max 4 BOOKED visits per technician per UTC calendar day.
    same_day = [v for v in booked if v['window_start'].date() == start.date()]
    if len(same_day) >= MAX_TECH_VISITS_PER_DAY:
        raise ApiError('ERR_TECHNICIAN_DAY_CAPACITY_REACHED', 409,
                       'technician already has 4 booked visits on that day')
    _recompute_available(plan)
    if plan['visits_available'] <= 0:
        raise ApiError('ERR_PLAN_EXHAUSTED', 409, 'plan has no visits available')
    rec = db.base_fields()
    rec.update({
        'plan_id': plan_id,
        'technician_id': technician_id,
        'window_start': start,
        'window_end': end,
        'status': 'BOOKED',
    })
    db.stores['visits'][rec['id']] = rec
    plan['visits_booked'] += 1
    _recompute_available(plan)
    db.touch(plan)
    return ok(ser_visit(rec), 201)


@bp.get('/piano-dealer/service-visits/<rid>')
def get_visit(rid):
    auth('ServiceCoordinator')
    return ok(ser_visit(find(db.stores['visits'], rid, 'service visit')))


@bp.get('/piano-dealer/service-visits')
def list_visits():
    auth('ServiceCoordinator')
    items = list(db.stores['visits'].values())
    plan_id = request.args.get('plan_id')
    technician_id = request.args.get('technician_id')
    if plan_id:
        items = [v for v in items if v['plan_id'] == plan_id]
    if technician_id:
        items = [v for v in items if v['technician_id'] == technician_id]
    return ok_list(items, ser_visit)


@bp.post('/piano-dealer/service-visits/<rid>/complete')
def complete_visit(rid):
    auth('ServiceCoordinator')
    visit = find(db.stores['visits'], rid, 'service visit')
    if visit['status'] != 'BOOKED':
        raise invalid('only BOOKED visits can be completed')
    visit['status'] = 'COMPLETED'
    db.touch(visit)
    plan = find(db.stores['plans'], visit['plan_id'], 'service plan')
    plan['visits_booked'] -= 1
    plan['visits_used'] += 1
    _recompute_available(plan)
    db.touch(plan)
    _auto_exhaust(plan)
    return ok(ser_visit(visit))


@bp.post('/piano-dealer/service-visits/<rid>/cancel')
def cancel_visit(rid):
    auth('ServiceCoordinator')
    visit = find(db.stores['visits'], rid, 'service visit')
    if visit['status'] != 'BOOKED':
        raise invalid('only BOOKED visits can be cancelled')
    visit['status'] = 'CANCELLED'
    db.touch(visit)
    plan = find(db.stores['plans'], visit['plan_id'], 'service plan')
    plan['visits_booked'] -= 1
    _recompute_available(plan)
    db.touch(plan)
    _auto_exhaust(plan)
    return ok(ser_visit(visit))
