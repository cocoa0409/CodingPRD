from flask import Blueprint, request

from db import db
from errors import ApiError
from middleware import authenticate, authorize, check_order_scope, ALL_ROLES
from response import ok
from services import calc
from services.lifecycle import (accepted_estimate_for, locked_coverage_for,
                                deliver_cascade, order_tariff, reevaluate_lot)
from services.store import new_entity, touch, order_view
from util import get_body, check_body, check_ref_exists, get_path, apply_list, now, midnight

bp = Blueprint('orders', __name__)


@bp.post('/orders')
def create_order():
    auth = authenticate()
    authorize(auth, ['BookingAgent'])
    body = get_body()
    check_ref_exists(body, 'customer_id', db.customers)
    check_ref_exists(body, 'tariff_id', db.tariffs)
    vals = check_body(body, [
        ('customer_id', 'str', True, None),
        ('tariff_id', 'str', True, None),
        ('pricing_mode', 'enum', True, ('BINDING', 'NON_BINDING')),
        ('origin_city', 'str', True, None),
        ('origin_state', 'str', True, None),
        ('destination_city', 'str', True, None),
        ('destination_state', 'str', True, None),
        ('mileage', 'int', True, (1, None)),
        ('pickup_date', 'datetime', True, None),
    ])
    tariff = db.tariffs[vals['tariff_id']]
    vals['pickup_date'] = midnight(vals['pickup_date'])  # PRD 2.5 day precision
    if tariff['status'] != 'PUBLISHED' or not (
            tariff['effective_start'] <= vals['pickup_date'] < tariff['effective_end']):
        raise ApiError('ERR_TARIFF_NOT_PUBLISHED', 409,
                       'tariff is not PUBLISHED or its window does not cover pickup_date')
    db.order_seq += 1
    order = new_entity()
    order.update({
        'order_number': 'VL-%06d' % db.order_seq,
        'customer_id': vals['customer_id'],
        'tariff_id': vals['tariff_id'],
        'pricing_mode': vals['pricing_mode'],
        'origin_city': vals['origin_city'],
        'origin_state': vals['origin_state'],
        'destination_city': vals['destination_city'],
        'destination_state': vals['destination_state'],
        'mileage': vals['mileage'],
        'pickup_date': vals['pickup_date'],
        'estimated_weight_lbs': None,
        'actual_weight_lbs': None,
        'authoritative_weight_ticket_id': None,
        'earliest_delivery_date': None,
        'latest_delivery_date': None,
        'delivered_at': None,
        'collected_at_delivery_cents': None,
        'final_charges_cents': None,
        'delivery_amount_due_cents': None,
        'deferred_balance_cents': None,
        'status': 'REGISTERED',
        'billing_status': 'UNBILLED',
    })
    db.orders[order['id']] = order
    # auto-create the CONFIRMED BOOKING assignment for the registering agent
    agent = db.agents[auth.user_id]
    asg = new_entity()
    asg.update({
        'order_id': order['id'],
        'agent_id': auth.user_id,
        'role': 'BOOKING',
        'split_pct': float(calc.split_pct_for('BOOKING', agent['commission_tier'])),
        'split_amount_cents': None,
        'status': 'CONFIRMED',
    })
    db.assignments[asg['id']] = asg
    return ok(order_view(order), 201)


@bp.get('/orders')
def list_orders():
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    filters = []
    for param in ('customer_id', 'tariff_id', 'authoritative_weight_ticket_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            filters.append(lambda o, p=param, v=v: o[p] == v)
    return apply_list(db.orders, filters, order_view)


@bp.get('/orders/<oid>')
def get_order(oid):
    auth = authenticate()
    authorize(auth, ALL_ROLES)
    return ok(order_view(get_path(db.orders, oid)))


@bp.post('/orders/<oid>/book')
def book_order(oid):
    auth = authenticate()
    authorize(auth, ['BookingAgent'])
    check_order_scope(auth, oid)
    order = get_path(db.orders, oid)
    check_body(get_body(), [])
    if order['status'] != 'REGISTERED':
        raise ApiError('ERR_ORDER_NOT_REGISTERED', 409, 'order is not REGISTERED')
    acc = [e for e in db.estimates.values()
           if e['order_id'] == oid and e['status'] == 'ACCEPTED'
           and e['estimate_kind'] == order['pricing_mode']]
    if not acc:
        raise ApiError('ERR_NO_ACCEPTED_ESTIMATE', 409,
                       'no ACCEPTED estimate matching the order pricing_mode')
    if not any(c for c in db.coverages.values()
               if c['order_id'] == oid and c['status'] == 'ELECTED'):
        raise ApiError('ERR_NO_VALUATION_COVERAGE', 409, 'no ELECTED valuation coverage')
    for role in ('BOOKING', 'ORIGIN', 'HAULING', 'DESTINATION'):
        if not any(a for a in db.assignments.values()
                   if a['order_id'] == oid and a['role'] == role and a['status'] == 'CONFIRMED'):
            raise ApiError('ERR_AGENT_ROLES_INCOMPLETE', 409,
                           'all four role assignments must be CONFIRMED')
    earliest, latest = calc.spread_window(order['mileage'], order['pickup_date'])
    order['earliest_delivery_date'] = earliest
    order['latest_delivery_date'] = latest
    order['status'] = 'BOOKED'
    touch(order)
    return ok(order_view(order))


@bp.post('/orders/<oid>/dispatch')
def dispatch_order(oid):
    auth = authenticate()
    authorize(auth, ['HaulingAgent'])
    check_order_scope(auth, oid)
    order = get_path(db.orders, oid)
    check_body(get_body(), [])
    if order['status'] != 'BOOKED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'order is not BOOKED')
    if not any(t for t in db.weight_tickets.values()
               if t['order_id'] == oid and t['ticket_kind'] == 'ORIGINAL'):
        raise ApiError('ERR_WEIGHT_TICKET_REQUIRED', 409, 'an ORIGINAL weight ticket is required')
    if any(c for c in db.crews.values()
           if c['order_id'] == oid and c['service_end'] == 'ORIGIN' and c['status'] == 'CONFIRMED'):
        raise ApiError('ERR_ORIGIN_SERVICES_INCOMPLETE', 409,
                       'a CONFIRMED origin crew assignment is not yet COMPLETED')
    if now() < order['pickup_date']:
        raise ApiError('ERR_PICKUP_DATE_NOT_REACHED', 422,
                       'logical clock has not reached pickup_date')
    acc = accepted_estimate_for(order)
    for c in db.coverages.values():
        if c['order_id'] == oid and c['status'] == 'ELECTED':
            c['status'] = 'LOCKED'
            touch(c)
    order['billing_status'] = 'PROVISIONALLY_BILLED'
    order['delivery_amount_due_cents'] = acc['estimated_charges_cents'] if acc else None
    order['status'] = 'IN_TRANSIT'
    touch(order)
    return ok(order_view(order))


@bp.post('/orders/<oid>/deliver')
def deliver_order(oid):
    auth = authenticate()
    authorize(auth, ['DestinationAgent'])
    check_order_scope(auth, oid)
    order = get_path(db.orders, oid)
    vals = check_body(get_body(), [('collected_at_delivery_cents', 'int', True, (0, None))])
    for lot in db.sit_lots.values():
        if lot['order_id'] == oid:
            reevaluate_lot(lot)
    in_storage = [l for l in db.sit_lots.values()
                  if l['order_id'] == oid and l['status'] == 'IN_STORAGE']
    # §3.5: a CONVERTED_PERMANENT lot does not block delivery — an IN_SIT order whose
    # lots have all converted is deliverable; an IN_SIT order with a stored lot is not.
    deliverable = order['status'] in ('IN_TRANSIT', 'OUT_FOR_DELIVERY') or (
        order['status'] == 'IN_SIT' and not in_storage)
    if not deliverable:
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409,
                       'order must be IN_TRANSIT or OUT_FOR_DELIVERY')
    if in_storage:
        raise ApiError('ERR_SHIPMENT_IN_STORAGE', 409, 'a SIT lot on the order is IN_STORAGE')
    if any(r for r in db.reweigh_requests.values()
           if r['order_id'] == oid and r['status'] == 'REQUESTED'):
        raise ApiError('ERR_REWEIGH_PENDING', 409,
                       'a re-weigh request is still REQUESTED; the customer must cancel it first')
    tariff = order_tariff(order)
    acc = accepted_estimate_for(order)
    locked = locked_coverage_for(order)
    locked_premium = locked['premium_cents'] if locked else 0
    charges = calc.final_charges(order, tariff, acc, locked_premium)
    if vals['collected_at_delivery_cents'] != charges['delivery_amount_due_cents']:
        raise ApiError('ERR_DELIVERY_PAYMENT_MISMATCH', 422,
                       'collected_at_delivery_cents must equal the recomputed delivery_amount_due_cents')
    order['final_charges_cents'] = charges['final_charges_cents']
    order['delivery_amount_due_cents'] = charges['delivery_amount_due_cents']
    order['deferred_balance_cents'] = charges['deferred_balance_cents']
    order['collected_at_delivery_cents'] = vals['collected_at_delivery_cents']
    order['delivered_at'] = now()
    if order['pricing_mode'] == 'BINDING':
        order['billing_status'] = 'PAID'
    else:
        order['billing_status'] = 'FINAL_BILLED'
    # PERFORMED re-weigh requests lapse to EXPIRED; original weight stands
    for r in db.reweigh_requests.values():
        if r['order_id'] == oid and r['status'] == 'PERFORMED':
            r['status'] = 'EXPIRED'
            touch(r)
    deliver_cascade(order, charges)
    order['status'] = 'DELIVERED'
    touch(order)
    return ok(order_view(order))


@bp.post('/orders/<oid>/close')
def close_order(oid):
    auth = authenticate()
    authorize(auth, ['VanLineAdmin'])
    order = get_path(db.orders, oid)
    check_body(get_body(), [])
    if order['status'] != 'SETTLED':
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409, 'order is not SETTLED')
    if any(c for c in db.claims.values()
           if c['order_id'] == oid and c['status'] in ('FILED', 'OFFER_MADE', 'DISPUTED', 'ACCEPTED')):
        raise ApiError('ERR_OPEN_CLAIMS_EXIST', 409, 'open claims exist on the order')
    claim_ids = {c['id'] for c in db.claims.values() if c['order_id'] == oid}
    stmt_ids = {s['id'] for s in db.statements.values() if s['order_id'] == oid}
    for d in db.disputes.values():
        if d['status'] in ('OPENED', 'RESPONSE_FILED', 'ARBITRATION_DOCKETED', 'DECIDED'):
            if d.get('claim_id') in claim_ids or d.get('revenue_statement_id') in stmt_ids:
                raise ApiError('ERR_OPEN_DISPUTES_EXIST', 409, 'open disputes exist on the order')
    order['status'] = 'CLOSED'
    touch(order)
    return ok(order_view(order))


@bp.post('/orders/<oid>/cancel')
def cancel_order(oid):
    auth = authenticate()
    authorize(auth, ['BookingAgent', 'VanLineAdmin'])
    check_order_scope(auth, oid)
    order = get_path(db.orders, oid)
    check_body(get_body(), [])
    if order['status'] not in ('REGISTERED', 'BOOKED'):
        raise ApiError('ERR_TRANSITION_NOT_ALLOWED', 409,
                       'only REGISTERED or BOOKED orders may be cancelled')
    for e in db.estimates.values():
        if e['order_id'] == oid and e['status'] in ('ISSUED', 'ACCEPTED'):
            e['status'] = 'VOIDED'
            touch(e)
    for c in db.coverages.values():
        if c['order_id'] == oid and c['status'] == 'ELECTED':
            c['status'] = 'SUPERSEDED'
            touch(c)
    for a in db.assignments.values():
        if a['order_id'] == oid and a['status'] in ('PROPOSED', 'CONFIRMED'):
            a['status'] = 'RELEASED'
            touch(a)
    for c in db.crews.values():
        if c['order_id'] == oid and c['status'] in ('REQUESTED', 'CONFIRMED'):
            c['status'] = 'CANCELLED'
            touch(c)
    order['status'] = 'CANCELLED'
    touch(order)
    return ok(order_view(order))


@bp.post('/orders/<oid>/payments')
def pay_order(oid):
    auth = authenticate()
    authorize(auth, ['Customer', 'VanLineAdmin'])
    check_order_scope(auth, oid)
    order = get_path(db.orders, oid)
    vals = check_body(get_body(), [('amount_cents', 'int', True, (0, None))])
    deferred = order['deferred_balance_cents'] or 0
    if order['billing_status'] != 'FINAL_BILLED' or deferred <= 0:
        raise ApiError('ERR_NO_BALANCE_DUE', 422, 'no deferred balance is due')
    if vals['amount_cents'] != deferred:
        raise ApiError('ERR_PAYMENT_AMOUNT_MISMATCH', 422,
                       'amount_cents must equal deferred_balance_cents')
    order['billing_status'] = 'PAID'
    touch(order)
    return ok(order_view(order))
