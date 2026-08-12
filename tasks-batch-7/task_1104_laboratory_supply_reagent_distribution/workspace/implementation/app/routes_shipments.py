"""Shipments and temperature excursions."""
from decimal import Decimal

from flask import Blueprint, request

from .db import db
from .errors import ApiError
from .response import ok
from . import serializers as S
from . import services as svc
from .validators import (
    get_context, require_role, get_body, check_unknown, as_str, as_int,
    as_number, as_enum, get_path_resource, check_body_id, paginate,
    apply_filters,
)

bp = Blueprint('shipments', __name__)
COOLANT_TYPES = ['NONE', 'GEL_PACK', 'DRY_ICE']
DECISIONS = ['ACCEPTED', 'DESTROYED', 'RETURNED']


def order_lines_for(order_id):
    return S.lines_of_order(order_id)


def hazmat_present(order_id):
    for l in order_lines_for(order_id):
        if db.products[l['product_id']]['hazard_class'] != 'NON_HAZARDOUS':
            return True
    return False


def temp_band(order_id):
    """storage_band_mapping: over lines with any status except CANCELLED."""
    mins, maxs = [], []
    for l in order_lines_for(order_id):
        if l['status'] == 'CANCELLED':
            continue
        band = svc.BANDS[db.products[l['product_id']]['storage_requirement']]
        mins.append(band[0])
        maxs.append(band[1])
    return (max(mins), min(maxs)) if mins else (None, None)


def affected_value_cents(order_id):
    total = 0
    for l in order_lines_for(order_id):
        p = db.products[l['product_id']]
        if p['requires_cold_chain']:
            total += l['line_total_cents'] or 0
    return total


def open_excursion_of(shipment_id):
    for e in db.excursions.values():
        if e['shipment_id'] == shipment_id and e['status'] == 'OPEN':
            return e
    return None


# ----------------------------------------------------------- shipments

@bp.route('/shipments', methods=['POST'])
def create_shipment():
    uid, role = get_context()
    require_role(role, ['InventoryClerk'])
    body = get_body()
    check_body_id(db.orders, body, 'order_id', 'ERR_ORDER_NOT_FOUND')
    check_unknown(body, ['order_id', 'coolant_type', 'coolant_units',
                         'declared_weight_grams'])
    order_id = as_str(body, 'order_id')
    coolant_type = as_enum(body, 'coolant_type', COOLANT_TYPES)
    coolant_units = as_int(body, 'coolant_units', required=False, default=0,
                           min_value=0)
    weight = as_int(body, 'declared_weight_grams', min_value=1)
    order = db.orders[order_id]
    if any(db.products[l['product_id']]['requires_cold_chain']
           for l in order_lines_for(order_id)) and coolant_units < 1:
        raise ApiError('ERR_INVALID_REQUEST',
                       'coolant_units must be >= 1 for cold-chain orders')
    # state: order must be ALLOCATED
    if order['status'] != 'ALLOCATED':
        raise ApiError('ERR_ORDER_NOT_ALLOCATED', 'Order is not ALLOCATED')
    warehouse = db.warehouses[order['warehouse_id']]
    lines = order_lines_for(order_id)
    # hazmat warehouse certification
    if any(db.products[l['product_id']]['hazard_class'] != 'NON_HAZARDOUS'
           for l in lines) and not warehouse['hazmat_certified']:
        raise ApiError('ERR_HAZMAT_WAREHOUSE_NOT_CERTIFIED',
                       'Warehouse is not hazmat certified')
    # hazmat load check: per-product cap, per-class caps, total cap, dry ice
    for l in lines:
        p = db.products[l['product_id']]
        if p['hazard_class'] != 'NON_HAZARDOUS' \
                and l['quantity'] > p['max_qty_per_shipment']:
            raise ApiError('ERR_HAZMAT_PRODUCT_LIMIT_EXCEEDED',
                           'Line quantity exceeds max_qty_per_shipment')
    class_load = {'FLAMMABLE': 0, 'CORROSIVE': 0, 'TOXIC': 0, 'OXIDIZER': 0}
    for l in lines:
        p = db.products[l['product_id']]
        if p['hazard_class'] in class_load:
            class_load[p['hazard_class']] += l['quantity'] * p['unit_haz_factor']
    for hc, load in class_load.items():
        if load > svc.HAZ_CLASS_CAP[hc]:
            raise ApiError('ERR_HAZMAT_CLASS_LIMIT_EXCEEDED',
                           'Hazard class %s load exceeds its cap' % hc)
    if sum(class_load.values()) > svc.TOTAL_HAZ_CAP:
        raise ApiError('ERR_HAZMAT_TOTAL_LIMIT_EXCEEDED',
                       'Aggregate hazmat load exceeds the total cap')
    if coolant_type == 'DRY_ICE' and coolant_units > svc.DRY_ICE_CAP:
        raise ApiError('ERR_DRY_ICE_LIMIT_EXCEEDED',
                       'Dry ice coolant units exceed the cap')
    # one shipment per order over its lifetime
    if S.shipment_of_order(order_id) is not None:
        raise ApiError('ERR_SHIPMENT_ALREADY_EXISTS',
                       'The order already has a shipment')
    tmin, tmax = temp_band(order_id)
    s = db.new_common()
    s.update({'order_id': order_id, 'coolant_type': coolant_type,
              'coolant_units': coolant_units, 'declared_weight_grams': weight,
              'actual_weight_grams': None, 'temp_min_celsius': tmin,
              'temp_max_celsius': tmax,
              'provisional_freight_cents': svc.freight_cost(
                  order['shipping_service'], weight, coolant_type,
                  coolant_units, hazmat_present(order_id),
                  order['product_total_cents']),
              'final_freight_cents': None, 'status': 'CREATED'})
    db.shipments[s['id']] = s
    return ok(S.shipment(s), 201)


@bp.route('/shipments', methods=['GET'])
def list_shipments():
    get_context()
    items = sorted(db.shipments.values(), key=lambda x: x['_seq'])
    items = apply_filters(items, {
        'order_id': request.args.get('order_id'),
        'status': request.args.get('status')})
    data, page = paginate(items, S.shipment)
    return ok(data, 200, page)


@bp.route('/shipments/<shipmentId>', methods=['GET'])
def get_shipment(shipmentId):
    get_context()
    s = get_path_resource(db.shipments, shipmentId, 'ERR_SHIPMENT_NOT_FOUND')
    return ok(S.shipment(s))


@bp.route('/shipments/<shipmentId>/pack', methods=['POST'])
def pack_shipment(shipmentId):
    uid, role = get_context()
    require_role(role, ['InventoryClerk'])
    s = get_path_resource(db.shipments, shipmentId, 'ERR_SHIPMENT_NOT_FOUND')
    get_body()
    if s['status'] != 'CREATED':
        raise ApiError('ERR_SHIPMENT_NOT_PACKABLE', 'Shipment is not CREATED')
    order = db.orders[s['order_id']]
    if order['status'] != 'ALLOCATED':
        raise ApiError('ERR_ORDER_NOT_ALLOCATED', 'Order is not ALLOCATED')
    touched = set()
    for res in db.reservations.values():
        line = db.order_lines.get(res['order_line_id'])
        if line and line['order_id'] == order['id'] and res['status'] == 'HELD':
            res['status'] = 'COMMITTED'
            db.touch('reservations', res['id'], touched)
    for line in order_lines_for(order['id']):
        if line['status'] == 'ALLOCATED':
            line['status'] = 'FULFILLED'
            db.touch('order_lines', line['id'], touched)
    order['status'] = 'PACKED'
    db.touch('orders', order['id'], touched)
    s['status'] = 'PACKED'
    db.touch('shipments', s['id'], touched)
    return ok(S.shipment(s))


@bp.route('/shipments/<shipmentId>/dispatch', methods=['POST'])
def dispatch_shipment(shipmentId):
    uid, role = get_context()
    require_role(role, ['InventoryClerk'])
    s = get_path_resource(db.shipments, shipmentId, 'ERR_SHIPMENT_NOT_FOUND')
    body = get_body()
    check_unknown(body, ['actual_weight_grams'])
    actual = as_int(body, 'actual_weight_grams', min_value=1)
    if s['status'] != 'PACKED':
        raise ApiError('ERR_SHIPMENT_NOT_DISPATCHABLE',
                       'Shipment is not PACKED')
    order = db.orders[s['order_id']]
    warehouse = db.warehouses[order['warehouse_id']]
    if warehouse['status'] != 'OPERATIONAL':
        raise ApiError('ERR_WAREHOUSE_NOT_OPERATIONAL',
                       'Warehouse is not OPERATIONAL')
    touched = set()
    s['actual_weight_grams'] = actual
    s['final_freight_cents'] = svc.freight_cost(
        order['shipping_service'], actual, s['coolant_type'],
        s['coolant_units'], hazmat_present(order['id']),
        order['product_total_cents'])
    for res in db.reservations.values():
        line = db.order_lines.get(res['order_line_id'])
        if line and line['order_id'] == order['id'] and res['status'] == 'COMMITTED':
            lot = db.lots[res['lot_id']]
            lot['quantity_reserved'] -= res['quantity']
            lot['quantity_consumed'] += res['quantity']
            db.touch('lots', lot['id'], touched)
            res['status'] = 'CONSUMED'
            db.touch('reservations', res['id'], touched)
    order['status'] = 'SHIPPED'
    db.touch('orders', order['id'], touched)
    customer = db.customers[order['customer_id']]
    db.touch('customers', customer['id'], touched)  # invoice posts
    svc.auto_suspend_check(customer, touched)
    for a in db.agreements.values():
        if a['status'] != 'ACTIVE' or a['customer_id'] != customer['id']:
            continue
        for line in order_lines_for(order['id']):
            if line['product_id'] == a['product_id']:
                a['stocked_quantity'] += line['quantity']
                db.touch('agreements', a['id'], touched)
    s['status'] = 'IN_TRANSIT'
    db.touch('shipments', s['id'], touched)
    return ok(S.shipment(s))


@bp.route('/shipments/<shipmentId>/record-temperature', methods=['POST'])
def record_temperature(shipmentId):
    uid, role = get_context()
    require_role(role, ['InventoryClerk'])
    s = get_path_resource(db.shipments, shipmentId, 'ERR_SHIPMENT_NOT_FOUND')
    body = get_body()
    check_unknown(body, ['temp_celsius', 'duration_minutes'])
    temp = as_number(body, 'temp_celsius')
    duration = as_int(body, 'duration_minutes', min_value=0)
    if s['status'] not in ('IN_TRANSIT', 'EXCURSION_HOLD'):
        raise ApiError('ERR_SHIPMENT_NOT_IN_TRANSIT',
                       'Shipment is not in transit')
    tmax, tmin = s['temp_max_celsius'], s['temp_min_celsius']
    if temp > tmax:
        deviation = temp - tmax
    elif temp < tmin:
        deviation = tmin - temp
    else:
        deviation = 0
    deviation = float(Decimal(str(deviation)).quantize(
        Decimal('0.1'), rounding='ROUND_HALF_UP'))
    if deviation == 0:
        return ok({'excursion_created': False, 'excursion_id': None,
                   'severity': None, 'shipment_status': s['status']}, 201)
    if open_excursion_of(s['id']) is not None:
        raise ApiError('ERR_EXCURSION_ALREADY_OPEN',
                       'An excursion of this shipment is still OPEN')
    if deviation > 5.0 or duration >= 240:
        severity = 'CRITICAL'
    elif deviation > 2.0 or duration >= 60:
        severity = 'MAJOR'
    else:
        severity = 'MINOR'
    affected = affected_value_cents(s['order_id'])
    touched = set()
    e = db.new_common()
    e.update({'shipment_id': s['id'], 'peak_temp_celsius': temp,
              'duration_minutes': duration, 'deviation_degrees': deviation,
              'severity': severity,
              'provisional_credit_cents': svc.rhu(
                  Decimal(affected) * Decimal('0.5')),
              'final_credit_cents': None, 'status': 'OPEN'})
    db.excursions[e['id']] = e
    s['status'] = 'EXCURSION_HOLD'
    db.touch('shipments', s['id'], touched)
    return ok({'excursion_created': True, 'excursion_id': e['id'],
               'severity': severity, 'shipment_status': s['status']}, 201)


@bp.route('/shipments/<shipmentId>/resume-transit', methods=['POST'])
def resume_transit(shipmentId):
    uid, role = get_context()
    require_role(role, ['InventoryClerk'])
    s = get_path_resource(db.shipments, shipmentId, 'ERR_SHIPMENT_NOT_FOUND')
    get_body()
    if s['status'] != 'EXCURSION_HOLD':
        raise ApiError('ERR_SHIPMENT_NOT_ON_HOLD',
                       'Shipment is not EXCURSION_HOLD')
    exs = sorted([e for e in db.excursions.values()
                  if e['shipment_id'] == s['id']], key=lambda e: e['_seq'])
    if not exs or exs[-1]['status'] != 'ACCEPTED':
        raise ApiError('ERR_EXCURSION_NOT_RESOLVED',
                       'The excursion has not been ACCEPTED')
    s['status'] = 'IN_TRANSIT'
    db.touch('shipments', s['id'], set())
    return ok(S.shipment(s))


@bp.route('/shipments/<shipmentId>/deliver', methods=['POST'])
def deliver_shipment(shipmentId):
    uid, role = get_context()
    require_role(role, ['InventoryClerk'])
    s = get_path_resource(db.shipments, shipmentId, 'ERR_SHIPMENT_NOT_FOUND')
    get_body()
    if s['status'] != 'IN_TRANSIT':
        raise ApiError('ERR_SHIPMENT_NOT_IN_TRANSIT',
                       'Shipment is not IN_TRANSIT')
    if open_excursion_of(s['id']) is not None:
        raise ApiError('ERR_DELIVERY_BLOCKED_OPEN_EXCURSION',
                       'An open excursion blocks delivery')
    touched = set()
    order = db.orders[s['order_id']]
    order['status'] = 'DELIVERED'
    db.touch('orders', order['id'], touched)
    s['status'] = 'DELIVERED'
    db.touch('shipments', s['id'], touched)
    return ok(S.shipment(s))


# ----------------------------------------------------------- excursions

@bp.route('/excursions', methods=['GET'])
def list_excursions():
    get_context()
    items = sorted(db.excursions.values(), key=lambda x: x['_seq'])
    sev = request.args.get('severity')
    items = apply_filters(items, {
        'shipment_id': request.args.get('shipment_id'),
        'status': request.args.get('status'),
        'severity': sev})
    data, page = paginate(items, S.excursion)
    return ok(data, 200, page)


@bp.route('/excursions/<excursionId>', methods=['GET'])
def get_excursion(excursionId):
    get_context()
    e = get_path_resource(db.excursions, excursionId, 'ERR_EXCURSION_NOT_FOUND')
    return ok(S.excursion(e))


@bp.route('/excursions/<excursionId>/disposition', methods=['POST'])
def disposition_excursion(excursionId):
    uid, role = get_context()
    require_role(role, ['QualityManager'])
    e = get_path_resource(db.excursions, excursionId, 'ERR_EXCURSION_NOT_FOUND')
    body = get_body()
    check_unknown(body, ['decision'])
    decision = as_enum(body, 'decision', DECISIONS)
    if e['status'] != 'OPEN':
        raise ApiError('ERR_EXCURSION_NOT_OPEN', 'Excursion is not OPEN')
    touched = set()
    shipment = db.shipments[e['shipment_id']]
    order = db.orders[shipment['order_id']]
    affected = affected_value_cents(order['id'])
    if decision == 'ACCEPTED':
        e['final_credit_cents'] = 0
    else:
        if decision == 'DESTROYED':
            e['final_credit_cents'] = affected
        else:  # RETURNED
            e['final_credit_cents'] = (shipment['final_freight_cents'] or 0) \
                + svc.rhu(Decimal(affected) * Decimal('0.25'))
        # cascade: shipment EXCURSION_HOLD -> RETURNED, order SHIPPED -> REFUNDED,
        # customer balance full invoice reversal
        shipment['status'] = 'RETURNED'
        db.touch('shipments', shipment['id'], touched)
        order['status'] = 'REFUNDED'
        db.touch('orders', order['id'], touched)
        db.touch('customers', order['customer_id'], touched)
    e['status'] = decision
    db.touch('excursions', e['id'], touched)
    return ok(S.excursion(e))
