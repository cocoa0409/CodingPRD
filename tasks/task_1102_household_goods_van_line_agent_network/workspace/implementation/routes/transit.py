from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import authenticate, authorize, check_order_scope, ALL_ROLES
from response import ok
from services import calc
from services.lifecycle import (accepted_estimate_for, locked_coverage_for,
                                order_tariff, reevaluate_lot)
from services.store import (new_entity, new_evidence, touch, weight_ticket_view,
                            reweigh_view, sit_lot_view)
from util import (get_body, check_body, check_ref_exists, get_path, apply_list,
                  now, to_cwt)

bp = Blueprint('transit', __name__)

REWEIGH_TERMINAL = ('APPLIED', 'DECLINED_BY_CUSTOMER', 'CANCELLED', 'EXPIRED')

SCALE_FIELDS = [
    ('scale_location', 'str', True, None),
    ('weighed_at', 'datetime', True, None),
    ('tare_weight_lbs', 'int', True, (1, None)),
    ('gross_weight_lbs', 'int', True, (1, None)),
]


def _make_ticket(order_id, kind, vals, reweigh_request_id, supersedes_ticket_id):
    if vals['gross_weight_lbs'] < vals['tare_weight_lbs']:
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'gross_weight_lbs must be >= tare_weight_lbs')
    t = new_evidence()
    t.update({
        'order_id': order_id,
        'reweigh_request_id': reweigh_request_id,
        'supersedes_ticket_id': supersedes_ticket_id,
        'ticket_kind': kind,
        'scale_location': vals['scale_location'],
        'weighed_at': vals['weighed_at'],
        'tare_weight_lbs': vals['tare_weight_lbs'],
        'gross_weight_lbs': vals['gross_weight_lbs'],
        'net_weight_lbs': vals['gross_weight_lbs'] - vals['tare_weight_lbs'],
    })
    db.weight_tickets[t['id']] = t
    return t


# ---------------------------------------------------------------------------
# Weight tickets
# ---------------------------------------------------------------------------

@bp.post('/orders/<oid>/weight-tickets')
def create_weight_ticket(oid):
    auth = authenticate()
    authorize(auth, ['HaulingAgent'])
    check_order_scope(auth, oid)
    order = get_path(db.orders, oid)
    vals = check_body(get_body(), SCALE_FIELDS)
    if order['status'] not in ('BOOKED', 'IN_TRANSIT'):
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409,
                       'original weighment requires the order to be BOOKED or IN_TRANSIT')
    if any(t for t in db.weight_tickets.values()
           if t['order_id'] == oid and t['ticket_kind'] == 'ORIGINAL'):
        raise ApiError('ERR_ORIGINAL_WEIGHT_EXISTS', 409,
                       'an ORIGINAL weight ticket already exists on this order')
    t = _make_ticket(oid, 'ORIGINAL', vals, None, None)
    order['authoritative_weight_ticket_id'] = t['id']
    order['actual_weight_lbs'] = t['net_weight_lbs']
    touch(order)
    return ok(weight_ticket_view(t), 201)


@bp.get('/weight-tickets')
def list_weight_tickets():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    for param in ('order_id', 'reweigh_request_id', 'supersedes_ticket_id', 'ticket_kind'):
        v = request.args.get(param)
        if v is not None:
            filters.append(lambda t, p=param, v=v: t[p] == v)
    return apply_list(db.weight_tickets, filters, weight_ticket_view)


@bp.get('/weight-tickets/<tid>')
def get_weight_ticket(tid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(weight_ticket_view(get_path(db.weight_tickets, tid)))


# ---------------------------------------------------------------------------
# Reweigh requests
# ---------------------------------------------------------------------------

@bp.post('/orders/<oid>/reweigh-requests')
def create_reweigh(oid):
    auth = authenticate()
    authorize(auth, ['Customer', 'BookingAgent'])
    check_order_scope(auth, oid)
    order = get_path(db.orders, oid)
    vals = check_body(get_body(), [
        ('requested_by_role', 'enum', True, ('CUSTOMER', 'BOOKING_AGENT')),
    ])
    if order['status'] != 'IN_TRANSIT':
        raise ApiError('ERR_ORDER_NOT_IN_TRANSIT', 409, 'order is not IN_TRANSIT')
    for r in db.reweigh_requests.values():
        if r['order_id'] != oid:
            continue
        if r['status'] not in REWEIGH_TERMINAL or r['status'] == 'APPLIED':
            raise ApiError('ERR_REWEIGH_ALREADY_USED', 409,
                           'a non-terminal re-weigh request exists or one was already APPLIED')
    req = new_entity()
    req.update({
        'order_id': oid,
        'requested_by_role': vals['requested_by_role'],
        'resulting_ticket_id': None,
        'status': 'REQUESTED',
    })
    db.reweigh_requests[req['id']] = req
    return ok(reweigh_view(req), 201)


@bp.post('/reweigh-requests/<rid>/perform')
def perform_reweigh(rid):
    auth = authenticate()
    authorize(auth, ['HaulingAgent'])
    req = get_path(db.reweigh_requests, rid)
    check_order_scope(auth, req['order_id'])
    vals = check_body(get_body(), SCALE_FIELDS)
    if req['status'] != 'REQUESTED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 're-weigh request is not REQUESTED')
    order = db.orders[req['order_id']]
    if order['status'] not in ('IN_TRANSIT', 'IN_SIT'):
        raise ApiError('ERR_ORDER_NOT_IN_TRANSIT', 409,
                       'order must be IN_TRANSIT or IN_SIT')
    t = _make_ticket(req['order_id'], 'REWEIGH', vals, rid,
                     order['authoritative_weight_ticket_id'])
    req['resulting_ticket_id'] = t['id']
    req['status'] = 'PERFORMED'
    touch(req)
    return ok(reweigh_view(req))


@bp.post('/reweigh-requests/<rid>/apply')
def apply_reweigh(rid):
    auth = authenticate()
    authorize(auth, ['Customer', 'VanLineAdmin'])
    req = get_path(db.reweigh_requests, rid)
    check_order_scope(auth, req['order_id'])
    check_body(get_body(), [])
    if req['status'] != 'PERFORMED':
        raise ApiError('ERR_REWEIGH_REQUEST_NOT_PERFORMED', 409,
                       're-weigh request is not PERFORMED')
    order = db.orders[req['order_id']]
    if order['status'] not in ('IN_TRANSIT', 'IN_SIT'):
        raise ApiError('ERR_ORDER_NOT_IN_TRANSIT', 409,
                       'order must be IN_TRANSIT or IN_SIT')
    ticket = db.weight_tickets[req['resulting_ticket_id']]
    order['authoritative_weight_ticket_id'] = ticket['id']
    order['actual_weight_lbs'] = ticket['net_weight_lbs']
    # refresh the delivery amount with the cap re-evaluated on the new weight
    tariff = order_tariff(order)
    acc = accepted_estimate_for(order)
    locked = locked_coverage_for(order)
    locked_premium = locked['premium_cents'] if locked else 0
    if acc is not None:
        charges = calc.final_charges(order, tariff, acc, locked_premium)
        order['delivery_amount_due_cents'] = charges['delivery_amount_due_cents']
    touch(order)
    req['status'] = 'APPLIED'
    touch(req)
    return ok(reweigh_view(req))


@bp.post('/reweigh-requests/<rid>/decline')
def decline_reweigh(rid):
    auth = authenticate()
    authorize(auth, ['Customer'])
    req = get_path(db.reweigh_requests, rid)
    check_order_scope(auth, req['order_id'])
    check_body(get_body(), [])
    if req['status'] != 'PERFORMED':
        raise ApiError('ERR_REWEIGH_REQUEST_NOT_PERFORMED', 409,
                       're-weigh request is not PERFORMED')
    req['status'] = 'DECLINED_BY_CUSTOMER'
    touch(req)
    return ok(reweigh_view(req))


@bp.post('/reweigh-requests/<rid>/cancel')
def cancel_reweigh(rid):
    auth = authenticate()
    authorize(auth, ['Customer', 'BookingAgent'])
    req = get_path(db.reweigh_requests, rid)
    check_order_scope(auth, req['order_id'])
    check_body(get_body(), [])
    if req['status'] != 'REQUESTED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 're-weigh request is not REQUESTED')
    req['status'] = 'CANCELLED'
    touch(req)
    return ok(reweigh_view(req))


@bp.get('/reweigh-requests')
def list_reweighs():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    for param in ('order_id', 'resulting_ticket_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            filters.append(lambda r, p=param, v=v: r[p] == v)
    return apply_list(db.reweigh_requests, filters, reweigh_view)


@bp.get('/reweigh-requests/<rid>')
def get_reweigh(rid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(reweigh_view(get_path(db.reweigh_requests, rid)))


# ---------------------------------------------------------------------------
# SIT lots
# ---------------------------------------------------------------------------

@bp.post('/orders/<oid>/sit-lots')
def create_sit_lot(oid):
    auth = authenticate()
    authorize(auth, ['HaulingAgent', 'DestinationAgent'])
    check_order_scope(auth, oid)
    order = get_path(db.orders, oid)
    body = get_body()
    check_ref_exists(body, 'warehouse_id', db.warehouses)
    vals = check_body(body, [('warehouse_id', 'str', True, None)])
    if order['status'] != 'IN_TRANSIT':
        raise ApiError('ERR_ORDER_NOT_IN_TRANSIT', 409, 'order is not IN_TRANSIT')
    wh = db.warehouses[vals['warehouse_id']]
    if wh['status'] != 'ACTIVE':
        raise ApiError('ERR_WAREHOUSE_INACTIVE', 409, 'warehouse is not ACTIVE')
    stored_cwt = to_cwt(order['actual_weight_lbs'] or 0)
    if wh['occupied_cwt'] + stored_cwt > wh['capacity_cwt']:
        raise ApiError('ERR_WAREHOUSE_CAPACITY_EXCEEDED', 409,
                       'warehouse aggregate capacity would be exceeded')
    lot = new_entity()
    lot.update({
        'order_id': oid,
        'warehouse_id': wh['id'],
        'stored_weight_cwt': stored_cwt,
        'checked_in_at': now(),
        'released_at': None,
        'days_stored': None,
        'accrued_storage_cents': None,
        'status': 'IN_STORAGE',
    })
    db.sit_lots[lot['id']] = lot
    wh['occupied_cwt'] += stored_cwt
    touch(wh)
    order['status'] = 'IN_SIT'
    touch(order)
    return ok(sit_lot_view(lot), 201)


@bp.post('/sit-lots/<lid>/release')
def release_sit_lot(lid):
    auth = authenticate()
    authorize(auth, ['DestinationAgent'])
    lot = get_path(db.sit_lots, lid)
    check_order_scope(auth, lot['order_id'])
    check_body(get_body(), [])
    # day-limit rule evaluated first: may auto-convert, which then fails the release
    reevaluate_lot(lot)
    if lot['status'] != 'IN_STORAGE':
        raise ApiError('ERR_LOT_NOT_IN_STORAGE', 409, 'SIT lot is not IN_STORAGE')
    order = db.orders[lot['order_id']]
    tariff = order_tariff(order)
    days = calc.sit_days(lot['checked_in_at'], now())
    lot['status'] = 'RELEASED'
    lot['released_at'] = now()
    lot['days_stored'] = days
    lot['accrued_storage_cents'] = calc.sit_accrual(
        lot['stored_weight_cwt'], tariff['sit_daily_rate_cents_per_cwt'], days)
    wh = db.warehouses.get(lot['warehouse_id'])
    if wh is not None:
        wh['occupied_cwt'] -= lot['stored_weight_cwt']
        touch(wh)
    touch(lot)
    if order['status'] == 'IN_SIT':
        order['status'] = 'OUT_FOR_DELIVERY'
        touch(order)
    return ok(sit_lot_view(lot))


@bp.get('/sit-lots')
def list_sit_lots():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    for param in ('order_id', 'warehouse_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            filters.append(lambda l, p=param, v=v: l[p] == v)
    for lot in db.sit_lots.values():
        reevaluate_lot(lot)
    return apply_list(db.sit_lots, filters, sit_lot_view)


@bp.get('/sit-lots/<lid>')
def get_sit_lot(lid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    lot = get_path(db.sit_lots, lid)
    reevaluate_lot(lot)
    return ok(sit_lot_view(lot))
