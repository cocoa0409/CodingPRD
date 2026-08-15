from datetime import timedelta

from flask import Blueprint, request

import calc
import db
from errors import ApiError, invalid, forbidden
from middleware import auth
from response import ok, ok_list
from util import body, require, optional, as_str, as_int, as_num, as_bool, as_list, find, serialize

bp = Blueprint('orders', __name__)

DT_FIELDS = ('delivered_at', 'installed_at')


def ser(order):
    return serialize(order, DT_FIELDS)


def _not_payable(message='order payment state does not permit this operation'):
    return ApiError('ERR_ORDER_NOT_PAYABLE', 409, message)


def _not_deliverable(message='order fulfillment state does not permit this operation'):
    return ApiError('ERR_DELIVERY_NOT_ACTIONABLE', 409, message)


def _validate_items(items_raw):
    items = as_list(items_raw, 'items')
    if len(items) < 1:
        raise invalid('items must contain at least one line')
    out = []
    for line in items:
        if not isinstance(line, dict):
            raise invalid('each item must be an object')
        out.append({
            'instrument_id': as_str(require(line, 'instrument_id'), 'instrument_id'),
            'unit_price_cents': as_int(require(line, 'unit_price_cents'), 'unit_price_cents'),
            'discount_pct': as_num(require(line, 'discount_pct'), 'discount_pct'),
        })
    return out


def _resolve_item_instruments(items):
    return [find(db.stores['instruments'], it['instrument_id'], 'instrument') for it in items]


def sell_order_instruments(order):
    """RESERVED -> SOLD for every line; consignment payouts posted to ledgers.
    Shared by full payment and financing approval."""
    payouts = []
    for item in order['items']:
        inst = find(db.stores['instruments'], item['instrument_id'], 'instrument')
        if inst['status'] == 'RESERVED':
            inst['status'] = 'SOLD'
            db.touch(inst)
        if inst['acquisition_type'] == 'CONSIGNMENT':
            line_total = calc.rhu(calc.D(item['unit_price_cents']) * (calc.D(1) - calc.D(item['discount_pct'])))
            consignor = db.stores['consignors'][inst['consignor_id']]
            payout = calc.consignment_payout(line_total, consignor, inst)
            consignor['outstanding_payout_cents'] += payout
            db.touch(consignor)
            payouts.append({'instrument_id': inst['id'], 'payout_cents': payout})
    order['_payouts'] = payouts


@bp.post('/piano-dealer/sales-orders')
def create_order():
    auth('SalesAssociate')
    d = body()
    customer_id = as_str(require(d, 'customer_id'), 'customer_id')
    items = _validate_items(require(d, 'items'))
    tax_rate = as_num(require(d, 'tax_rate'), 'tax_rate')
    distance_miles = as_int(require(d, 'distance_miles'), 'distance_miles')
    stairs_count = as_int(require(d, 'stairs_count'), 'stairs_count')
    climate = as_bool(require(d, 'climate_controlled_required'), 'climate_controlled_required')
    trade_in_id = optional(d, 'trade_in_appraisal_id')
    bid_id = optional(d, 'bid_package_id')
    find(db.stores['customers'], customer_id, 'customer')
    instruments = _resolve_item_instruments(items)
    appraisal = find(db.stores['appraisals'], trade_in_id, 'appraisal') if trade_in_id else None
    bid = find(db.stores['bids'], bid_id, 'bid package') if bid_id else None
    # State (priority 5): every line instrument must be AVAILABLE.
    for inst in instruments:
        if inst['status'] != 'AVAILABLE':
            raise ApiError('ERR_INSTRUMENT_NOT_AVAILABLE', 409,
                           'instrument %s is not AVAILABLE' % inst['id'])
    # Referenced-object state (priority 9).
    if appraisal is not None and (appraisal['status'] != 'ACCEPTED'
                                  or appraisal['customer_id'] != customer_id):
        raise ApiError('ERR_TRADE_IN_NOT_ACCEPTED', 422,
                       'trade-in appraisal must be ACCEPTED and owned by the customer')
    if bid is not None and (bid['status'] != 'AWARDED' or bid['customer_id'] != customer_id):
        raise ApiError('ERR_BID_NOT_ACTIONABLE', 409,
                       'bid package must be AWARDED and owned by the customer')
    pricing = calc.order_pricing(items, appraisal, tax_rate, distance_miles, stairs_count, climate)
    rec = db.base_fields()
    rec.update({
        'customer_id': customer_id,
        'items': items,
        'trade_in_appraisal_id': trade_in_id,
        'bid_package_id': bid_id,
        'tax_rate': tax_rate,
        'distance_miles': distance_miles,
        'stairs_count': stairs_count,
        'climate_controlled_required': climate,
        'subtotal_cents': pricing['subtotal_cents'],
        'trade_in_credit_cents': pricing['trade_in_credit_cents'],
        'delivery_fee_cents': pricing['delivery_fee_cents'],
        'tax_cents': pricing['tax_cents'],
        'total_cents': pricing['total_cents'],
        'amount_paid_cents': 0,
        'balance_cents': pricing['total_cents'],
        'payment_status': 'UNPAID',
        'fulfillment_status': 'AWAITING_SCHEDULING',
        'delivered_at': None,
        'installed_at': None,
        '_payouts': [],
    })
    db.stores['orders'][rec['id']] = rec
    for inst in instruments:
        inst['status'] = 'RESERVED'
        db.touch(inst)
    return ok(ser(rec), 201)


@bp.get('/piano-dealer/sales-orders/<rid>')
def get_order(rid):
    uid, role = auth('SalesAssociate', 'StoreManager', 'FinanceOfficer', 'ServiceCoordinator', 'Customer')
    order = find(db.stores['orders'], rid, 'order')
    if role == 'Customer' and order['customer_id'] != uid:
        raise forbidden('customer may only read their own orders')
    return ok(ser(order))


@bp.get('/piano-dealer/sales-orders')
def list_orders():
    auth('SalesAssociate', 'StoreManager', 'FinanceOfficer')
    items = list(db.stores['orders'].values())
    customer_id = request.args.get('customer_id')
    trade_in_id = request.args.get('trade_in_appraisal_id')
    bid_id = request.args.get('bid_package_id')
    if customer_id:
        items = [o for o in items if o['customer_id'] == customer_id]
    if trade_in_id:
        items = [o for o in items if o.get('trade_in_appraisal_id') == trade_in_id]
    if bid_id:
        items = [o for o in items if o.get('bid_package_id') == bid_id]
    return ok_list(items, ser)


@bp.patch('/piano-dealer/sales-orders/<rid>')
def amend_order(rid):
    auth('SalesAssociate')
    order = find(db.stores['orders'], rid, 'order')
    d = body()
    expected = as_int(require(d, 'expected_order_version'), 'expected_order_version')
    if order['payment_status'] != 'UNPAID':
        raise _not_payable('only UNPAID orders can be amended')
    if expected != order['version']:
        raise ApiError('ERR_STALE_VERSION', 412, 'expected_order_version is stale')
    new_items = None
    new_instruments = None
    if 'items' in d and d['items'] is not None:
        new_items = _validate_items(d['items'])
        new_instruments = _resolve_item_instruments(new_items)
        old_ids = {it['instrument_id'] for it in order['items']}
        for inst in new_instruments:
            # An instrument already reserved by this order is released then re-reserved.
            if inst['status'] != 'AVAILABLE' and inst['id'] not in old_ids:
                raise ApiError('ERR_INSTRUMENT_NOT_AVAILABLE', 409,
                               'instrument %s is not AVAILABLE' % inst['id'])
    if 'tax_rate' in d and d['tax_rate'] is not None:
        order['tax_rate'] = as_num(d['tax_rate'], 'tax_rate')
    if 'distance_miles' in d and d['distance_miles'] is not None:
        order['distance_miles'] = as_int(d['distance_miles'], 'distance_miles')
    if 'stairs_count' in d and d['stairs_count'] is not None:
        order['stairs_count'] = as_int(d['stairs_count'], 'stairs_count')
    if 'climate_controlled_required' in d and d['climate_controlled_required'] is not None:
        order['climate_controlled_required'] = as_bool(d['climate_controlled_required'],
                                                       'climate_controlled_required')
    if new_items is not None:
        for inst in _resolve_item_instruments(order['items']):
            if inst['status'] == 'RESERVED':
                inst['status'] = 'AVAILABLE'
                db.touch(inst)
        order['items'] = new_items
        for inst in new_instruments:
            inst['status'] = 'RESERVED'
            db.touch(inst)
    appraisal = (find(db.stores['appraisals'], order['trade_in_appraisal_id'], 'appraisal')
                 if order.get('trade_in_appraisal_id') else None)
    pricing = calc.order_pricing(order['items'], appraisal, order['tax_rate'],
                                 order['distance_miles'], order['stairs_count'],
                                 order['climate_controlled_required'])
    order['subtotal_cents'] = pricing['subtotal_cents']
    order['trade_in_credit_cents'] = pricing['trade_in_credit_cents']
    order['delivery_fee_cents'] = pricing['delivery_fee_cents']
    order['tax_cents'] = pricing['tax_cents']
    order['total_cents'] = pricing['total_cents']
    order['balance_cents'] = order['total_cents'] - order['amount_paid_cents']
    db.touch(order)
    return ok(ser(order))


@bp.post('/piano-dealer/sales-orders/<rid>/payments')
def post_payment(rid):
    auth('SalesAssociate')
    order = find(db.stores['orders'], rid, 'order')
    d = body()
    amount = as_int(require(d, 'amount_cents'), 'amount_cents')
    as_str(require(d, 'method'), 'method')
    if amount <= 0:
        raise invalid('amount_cents must be positive')
    if order['payment_status'] not in ('UNPAID', 'DEPOSIT_PAID'):
        raise _not_payable('order is not payable in its current state')
    if amount > order['balance_cents']:
        raise ApiError('ERR_OVERPAYMENT', 422, 'payment exceeds the order balance')
    order['amount_paid_cents'] += amount
    order['balance_cents'] = order['total_cents'] - order['amount_paid_cents']
    if order['balance_cents'] == 0:
        order['payment_status'] = 'PAID_IN_FULL'
        sell_order_instruments(order)
    else:
        order['payment_status'] = 'DEPOSIT_PAID'
    db.touch(order)
    return ok(ser(order))


@bp.post('/piano-dealer/sales-orders/<rid>/confirm-installation')
def confirm_installation(rid):
    uid, role = auth('StoreManager', 'Customer')
    order = find(db.stores['orders'], rid, 'order')
    if role == 'Customer' and order['customer_id'] != uid:
        raise forbidden('customer may only confirm installation on their own order')
    if order['fulfillment_status'] != 'DELIVERED':
        raise _not_deliverable('order must be DELIVERED to confirm installation')
    order['fulfillment_status'] = 'INSTALLED'
    order['installed_at'] = db.now()
    db.touch(order)
    return ok(ser(order))


@bp.post('/piano-dealer/sales-orders/<rid>/complete-return')
def complete_return(rid):
    auth('StoreManager')
    order = find(db.stores['orders'], rid, 'order')
    if order['fulfillment_status'] != 'INSTALLED':
        raise _not_deliverable('order must be INSTALLED to complete a return')
    if order['payment_status'] != 'PAID_IN_FULL':
        raise _not_payable('order must be PAID_IN_FULL to complete a return')
    if db.now() > order['installed_at'] + timedelta(days=14):
        raise ApiError('ERR_RETURN_WINDOW_CLOSED', 422,
                       'the 14-day return window has closed')
    # Full unwind cascade.
    order['payment_status'] = 'REFUNDED'
    order['fulfillment_status'] = 'RETURNED'
    db.touch(order)
    instrument_ids = []
    for item in order['items']:
        inst = find(db.stores['instruments'], item['instrument_id'], 'instrument')
        inst['status'] = 'IN_PREP'
        db.touch(inst)
        instrument_ids.append(inst['id'])
    customer = find(db.stores['customers'], order['customer_id'], 'customer')
    voided = 0
    for w in db.stores['warranties'].values():
        if w['instrument_id'] in instrument_ids and w['status'] == 'REGISTERED':
            w['status'] = 'VOID'
            db.touch(w)
            voided += 1
    if voided:
        customer['risk_score'] = min(850, max(300, customer['risk_score'] - 25 * voided))
        db.touch(customer)
    for a in db.stores['agreements'].values():
        if a['order_id'] == order['id'] and a['status'] == 'ACTIVE':
            a['status'] = 'CANCELLED'
            db.touch(a)
    # Compensating reversal of consignment payouts posted at sale.
    for p in order.get('_payouts', []):
        inst = db.stores['instruments'].get(p['instrument_id'])
        if inst and inst.get('consignor_id'):
            consignor = db.stores['consignors'].get(inst['consignor_id'])
            if consignor:
                consignor['outstanding_payout_cents'] -= p['payout_cents']
                db.touch(consignor)
    order['_payouts'] = []
    return ok(ser(order))


@bp.post('/piano-dealer/sales-orders/<rid>/cancel')
def cancel_order(rid):
    auth('SalesAssociate')
    order = find(db.stores['orders'], rid, 'order')
    if order['payment_status'] != 'UNPAID':
        raise _not_payable('only UNPAID orders can be cancelled')
    if order['fulfillment_status'] != 'AWAITING_SCHEDULING':
        raise _not_deliverable('only AWAITING_SCHEDULING orders can be cancelled')
    order['fulfillment_status'] = 'CANCELLED'
    db.touch(order)
    for item in order['items']:
        inst = find(db.stores['instruments'], item['instrument_id'], 'instrument')
        if inst['status'] == 'RESERVED':
            inst['status'] = 'AVAILABLE'
            db.touch(inst)
    return ok(ser(order))
