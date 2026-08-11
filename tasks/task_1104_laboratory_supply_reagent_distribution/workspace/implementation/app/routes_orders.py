"""Customer accounts, orders, order lines, lot reservations."""
from flask import Blueprint, request

from .db import db
from .errors import ApiError
from .response import ok
from . import serializers as S
from . import services as svc
from .validators import (
    get_context, require_role, get_body, check_unknown, as_str, as_bool,
    as_int, as_number, as_enum, as_date, get_path_resource, check_body_id,
    id_or_none, paginate, apply_filters,
)

bp = Blueprint('orders', __name__)
ENDORSEMENTS = ['NONE', 'LIMITED', 'FULL']
SHIPPING_SERVICES = ['STANDARD', 'EXPRESS', 'PRIORITY_OVERNIGHT']
FULFILLMENT_MODES = ['ANY', 'SEQUENTIAL']


def own_or_403(resource_customer_id, uid, role):
    if role == 'Customer' and resource_customer_id != uid:
        raise ApiError('ERR_RESOURCE_OWNERSHIP_VIOLATION',
                       'Resource belongs to a different customer')


# ----------------------------------------------------------- customers

@bp.route('/customers', methods=['POST'])
def create_customer():
    uid, role = get_context()
    require_role(role, ['AccountManager'])
    body = get_body()
    check_unknown(body, ['name', 'credit_limit_cents', 'volume_discount_pct',
                         'hazmat_endorsement', 'cold_chain_certified'])
    name = as_str(body, 'name')
    limit = as_int(body, 'credit_limit_cents', min_value=1)
    vdp = as_number(body, 'volume_discount_pct', required=False, default=0,
                    min_value=0, max_value=0.5)
    end = as_enum(body, 'hazmat_endorsement', ENDORSEMENTS, required=False,
                  default='NONE')
    ccc = as_bool(body, 'cold_chain_certified', required=False, default=False)
    c = db.new_common()
    c.update({'name': name, 'credit_limit_cents': limit,
              'volume_discount_pct': vdp, 'hazmat_endorsement': end,
              'cold_chain_certified': ccc, 'status': 'ACTIVE'})
    db.customers[c['id']] = c
    return ok(S.customer(c), 201)


@bp.route('/customers', methods=['GET'])
def list_customers():
    uid, role = get_context()
    items = sorted(db.customers.values(), key=lambda x: x['_seq'])
    if role == 'Customer':
        items = [c for c in items if c['id'] == uid]
    items = apply_filters(items, {'status': request.args.get('status')})
    data, page = paginate(items, S.customer)
    return ok(data, 200, page)


@bp.route('/customers/<customerId>', methods=['GET'])
def get_customer(customerId):
    uid, role = get_context()
    c = db.customers.get(customerId)
    if c is not None and role == 'Customer' and c['id'] != uid:
        raise ApiError('ERR_RESOURCE_OWNERSHIP_VIOLATION',
                       'Resource belongs to a different customer')
    c = get_path_resource(db.customers, customerId, 'ERR_CUSTOMER_NOT_FOUND')
    return ok(S.customer(c))


@bp.route('/customers/<customerId>', methods=['PATCH'])
def update_customer(customerId):
    uid, role = get_context()
    require_role(role, ['AccountManager'])
    c = get_path_resource(db.customers, customerId, 'ERR_CUSTOMER_NOT_FOUND')
    body = get_body()
    check_unknown(body, ['credit_limit_cents', 'volume_discount_pct',
                         'hazmat_endorsement', 'cold_chain_certified',
                         'expected_customer_version'])
    limit = as_int(body, 'credit_limit_cents', required=False, min_value=1)
    vdp = as_number(body, 'volume_discount_pct', required=False,
                    min_value=0, max_value=0.5)
    end = as_enum(body, 'hazmat_endorsement', ENDORSEMENTS, required=False)
    ccc = as_bool(body, 'cold_chain_certified', required=False)
    expected = as_int(body, 'expected_customer_version')
    if expected != c['version']:
        raise ApiError('ERR_STALE_CUSTOMER_VERSION',
                       'expected_customer_version does not match')
    touched = set()
    if limit is not None:
        c['credit_limit_cents'] = limit
    if vdp is not None:
        c['volume_discount_pct'] = vdp
    if end is not None:
        c['hazmat_endorsement'] = end
    if ccc is not None:
        c['cold_chain_certified'] = ccc
    db.touch('customers', c['id'], touched)
    return ok(S.customer(c))


@bp.route('/customers/<customerId>/suspend', methods=['POST'])
def suspend_customer(customerId):
    uid, role = get_context()
    require_role(role, ['AccountManager'])
    c = get_path_resource(db.customers, customerId, 'ERR_CUSTOMER_NOT_FOUND')
    get_body()
    if c['status'] != 'ACTIVE':
        raise ApiError('ERR_CUSTOMER_NOT_ACTIVE', 'Customer is not ACTIVE')
    c['status'] = 'SUSPENDED'
    db.touch('customers', c['id'], set())
    return ok(S.customer(c))


@bp.route('/customers/<customerId>/reactivate', methods=['POST'])
def reactivate_customer(customerId):
    uid, role = get_context()
    require_role(role, ['AccountManager'])
    c = get_path_resource(db.customers, customerId, 'ERR_CUSTOMER_NOT_FOUND')
    get_body()
    if c['status'] != 'SUSPENDED':
        raise ApiError('ERR_CUSTOMER_NOT_SUSPENDED', 'Customer is not SUSPENDED')
    if S.outstanding_balance(c['id']) > c['credit_limit_cents']:
        raise ApiError('ERR_OUTSTANDING_ABOVE_LIMIT',
                       'Outstanding balance exceeds the credit limit')
    c['status'] = 'ACTIVE'
    db.touch('customers', c['id'], set())
    return ok(S.customer(c))


@bp.route('/customers/<customerId>/close', methods=['POST'])
def close_customer(customerId):
    uid, role = get_context()
    require_role(role, ['AccountManager'])
    c = get_path_resource(db.customers, customerId, 'ERR_CUSTOMER_NOT_FOUND')
    get_body()
    if c['status'] not in ('ACTIVE', 'SUSPENDED'):
        raise ApiError('ERR_CUSTOMER_ALREADY_CLOSED', 'Customer is already CLOSED')
    for o in db.orders.values():
        if o['customer_id'] == c['id'] and o['status'] in (
                'DRAFT', 'ALLOCATED', 'BACKORDERED', 'PACKED', 'SHIPPED'):
            raise ApiError('ERR_OPEN_ORDERS_EXIST',
                           'Customer has open orders')
    for a in db.agreements.values():
        if a['customer_id'] == c['id'] and a['status'] == 'ACTIVE':
            raise ApiError('ERR_OPEN_AGREEMENTS_EXIST',
                           'Customer has an ACTIVE consignment agreement')
    if S.outstanding_balance(c['id']) != 0:
        raise ApiError('ERR_OUTSTANDING_BALANCE_NONZERO',
                       'Outstanding balance is not zero')
    c['status'] = 'CLOSED'
    db.touch('customers', c['id'], set())
    return ok(S.customer(c))


@bp.route('/customers/<customerId>/payments', methods=['POST'])
def record_payment(customerId):
    uid, role = get_context()
    require_role(role, ['AccountManager'])
    c = get_path_resource(db.customers, customerId, 'ERR_CUSTOMER_NOT_FOUND')
    body = get_body()
    check_unknown(body, ['amount_cents'])
    amount = as_int(body, 'amount_cents', min_value=1)
    db.payments.append({'customer_id': c['id'], 'amount_cents': amount})
    db.touch('customers', c['id'], set())
    return ok(S.customer(c), 201)


# ----------------------------------------------------------- orders

@bp.route('/orders', methods=['POST'])
def create_order():
    uid, role = get_context()
    require_role(role, ['Customer'])
    body = get_body()
    # stage 3 ownership on body customer_id (when evaluable)
    cid = id_or_none(body, 'customer_id')
    if cid is not None and cid != uid:
        raise ApiError('ERR_RESOURCE_OWNERSHIP_VIOLATION',
                       'Order customer_id must equal X-User-ID')
    # stage 4 existence in declared input order
    check_body_id(db.customers, body, 'customer_id', 'ERR_CUSTOMER_NOT_FOUND')
    check_body_id(db.warehouses, body, 'warehouse_id', 'ERR_WAREHOUSE_NOT_FOUND')
    lines_raw = body.get('lines')
    if isinstance(lines_raw, list):
        for entry in lines_raw:
            if isinstance(entry, dict):
                pid = entry.get('product_id')
                if isinstance(pid, str) and pid not in db.products:
                    raise ApiError('ERR_PRODUCT_NOT_FOUND',
                                   'Product %s does not exist' % pid)
    check_unknown(body, ['customer_id', 'warehouse_id', 'shipping_service',
                         'requested_ship_date', 'lines'])
    customer_id = as_str(body, 'customer_id')
    warehouse_id = as_str(body, 'warehouse_id')
    service = as_enum(body, 'shipping_service', SHIPPING_SERVICES)
    ship_date = as_date(body, 'requested_ship_date')
    if 'lines' not in body or not isinstance(body['lines'], list):
        raise ApiError('ERR_INVALID_REQUEST', 'lines must be an array')
    specs = []
    for entry in body['lines']:
        if not isinstance(entry, dict):
            raise ApiError('ERR_INVALID_REQUEST', 'line entries must be objects')
        check_unknown(entry, ['product_id', 'quantity', 'fulfillment_mode'])
        pid = as_str(entry, 'product_id')
        qty = as_int(entry, 'quantity', min_value=1)
        mode = as_enum(entry, 'fulfillment_mode', FULFILLMENT_MODES,
                       required=False, default='ANY')
        specs.append({'product_id': pid, 'quantity': qty,
                      'fulfillment_mode': mode})
    o = svc.create_order_record(customer_id, warehouse_id, service, ship_date,
                                specs)
    return ok(S.order(o), 201)


def order_visible_or_404(orderId, uid, role):
    o = db.orders.get(orderId)
    if o is not None and role == 'Customer':
        own_or_403(o['customer_id'], uid, role)
    return get_path_resource(db.orders, orderId, 'ERR_ORDER_NOT_FOUND')


@bp.route('/orders', methods=['GET'])
def list_orders():
    uid, role = get_context()
    items = sorted(db.orders.values(), key=lambda x: x['_seq'])
    if role == 'Customer':
        items = [o for o in items if o['customer_id'] == uid]
    items = apply_filters(items, {
        'customer_id': request.args.get('customer_id'),
        'warehouse_id': request.args.get('warehouse_id'),
        'status': request.args.get('status')})
    data, page = paginate(items, S.order)
    return ok(data, 200, page)


@bp.route('/orders/<orderId>', methods=['GET'])
def get_order(orderId):
    uid, role = get_context()
    o = order_visible_or_404(orderId, uid, role)
    return ok(S.order(o))


@bp.route('/orders/<orderId>/submit', methods=['POST'])
def submit_order_route(orderId):
    uid, role = get_context()
    require_role(role, ['Customer'])
    o = db.orders.get(orderId)
    if o is not None:
        own_or_403(o['customer_id'], uid, role)
    o = get_path_resource(db.orders, orderId, 'ERR_ORDER_NOT_FOUND')
    get_body()
    touched = set()
    svc.submit_order(o, touched)
    return ok(S.order(o))


@bp.route('/orders/<orderId>/reallocate', methods=['POST'])
def reallocate_order(orderId):
    uid, role = get_context()
    require_role(role, ['Customer'])
    o = db.orders.get(orderId)
    if o is not None:
        own_or_403(o['customer_id'], uid, role)
    o = get_path_resource(db.orders, orderId, 'ERR_ORDER_NOT_FOUND')
    body = get_body()
    check_unknown(body, ['expected_order_version'])
    expected = as_int(body, 'expected_order_version')
    if expected != o['version']:
        raise ApiError('ERR_STALE_ORDER_VERSION',
                       'expected_order_version does not match')
    if o['status'] not in ('BACKORDERED', 'ALLOCATED'):
        raise ApiError('ERR_ORDER_NOT_REALLOCATABLE',
                       'Order is not BACKORDERED or ALLOCATED')
    touched = set()
    # release every HELD reservation on the order, then re-run from scratch
    for res in list(db.reservations.values()):
        line = db.order_lines.get(res['order_line_id'])
        if line and line['order_id'] == o['id'] and res['status'] == 'HELD':
            svc._release_held_reservation(res, touched)
    for line in S.lines_of_order(o['id']):
        line['status'] = 'PENDING'
        db.touch('order_lines', line['id'], touched)
    for line in S.lines_of_order(o['id']):
        need = line['quantity'] - S.allocated_quantity(line['id'])
        if need <= 0:
            continue
        if line['fulfillment_mode'] == 'SEQUENTIAL':
            svc.allocate_sequential(o, line, need, touched)
        else:
            svc.allocate_any(o, line, need, touched)
    all_full = True
    for line in S.lines_of_order(o['id']):
        svc.set_line_status_from_allocation(line, touched)
        if S.allocated_quantity(line['id']) < line['quantity']:
            all_full = False
    o['status'] = 'ALLOCATED' if all_full else 'BACKORDERED'
    db.touch('orders', o['id'], touched)
    return ok(S.order(o))


@bp.route('/orders/<orderId>/cancel', methods=['POST'])
def cancel_order(orderId):
    uid, role = get_context()
    require_role(role, ['Customer'])
    o = db.orders.get(orderId)
    if o is not None:
        own_or_403(o['customer_id'], uid, role)
    o = get_path_resource(db.orders, orderId, 'ERR_ORDER_NOT_FOUND')
    get_body()
    if o['status'] not in ('DRAFT', 'BACKORDERED', 'ALLOCATED'):
        raise ApiError('ERR_ORDER_NOT_CANCELLABLE',
                       'Order cannot be cancelled in its current state')
    touched = set()
    for res in list(db.reservations.values()):
        line = db.order_lines.get(res['order_line_id'])
        if line and line['order_id'] == o['id'] and res['status'] == 'HELD':
            svc._release_held_reservation(res, touched)
    for line in S.lines_of_order(o['id']):
        line['status'] = 'CANCELLED'
        db.touch('order_lines', line['id'], touched)
    o['status'] = 'CANCELLED'
    db.touch('orders', o['id'], touched)
    return ok(S.order(o))


@bp.route('/orders/<orderId>/cost-summary', methods=['GET'])
def cost_summary(orderId):
    uid, role = get_context()
    o = order_visible_or_404(orderId, uid, role)
    customer = db.customers[o['customer_id']]
    ship = S.shipment_of_order(o['id'])
    product_total = o['product_total_cents']
    projected_total = product_total if product_total is not None \
        else svc.projected_product_total(o, customer)
    prov = ship['provisional_freight_cents'] if ship else None
    fin = ship['final_freight_cents'] if ship else None
    freight_known = fin if fin is not None else prov
    ratio = None
    if freight_known is not None and product_total:
        ratio = freight_known / product_total
    freight_projection = fin if fin is not None else (
        prov if prov is not None else (
            0 if projected_total >= svc.FREE_FREIGHT_THRESHOLD_CENTS
            else max(svc.BASE_FREIGHT[o['shipping_service']],
                     svc.MIN_FREIGHT_CENTS)))
    # projected_outstanding_cents: the customer's balance with this order's
    # impact accounted. The invoice posts exactly once at dispatch (SHIPPED /
    # DELIVERED already include it in the derived balance); CANCELLED and
    # REFUNDED orders contribute nothing now or later. Only pre-invoice
    # states add the order's projected impact on top of the current balance.
    balance = S.outstanding_balance(customer['id'])
    if o['status'] in ('SHIPPED', 'DELIVERED', 'CANCELLED', 'REFUNDED'):
        projected_outstanding = balance
    else:
        projected_outstanding = balance + projected_total + freight_projection
    data = {
        'product_total_cents': product_total,
        'provisional_freight_cents': prov,
        'final_freight_cents': fin,
        'freight_to_product_ratio': ratio,
        'projected_outstanding_cents': projected_outstanding,
    }
    return ok(data)


# ----------------------------------------------------------- order lines

def order_line_visible_or_404(lineId, uid, role):
    # OrderLine carries no customer_id field -> no Customer read scoping (§2.1)
    return get_path_resource(db.order_lines, lineId, 'ERR_ORDER_LINE_NOT_FOUND')


@bp.route('/order-lines', methods=['GET'])
def list_order_lines():
    uid, role = get_context()
    items = sorted(db.order_lines.values(), key=lambda x: x['_seq'])
    items = apply_filters(items, {
        'order_id': request.args.get('order_id'),
        'product_id': request.args.get('product_id'),
        'status': request.args.get('status')})
    data, page = paginate(items, S.order_line)
    return ok(data, 200, page)


@bp.route('/order-lines/<orderLineId>', methods=['GET'])
def get_order_line(orderLineId):
    uid, role = get_context()
    l = order_line_visible_or_404(orderLineId, uid, role)
    return ok(S.order_line(l))


# ----------------------------------------------------------- reservations

@bp.route('/reservations', methods=['GET'])
def list_reservations():
    uid, role = get_context()
    items = sorted(db.reservations.values(), key=lambda x: x['_seq'])
    items = apply_filters(items, {
        'order_line_id': request.args.get('order_line_id'),
        'lot_id': request.args.get('lot_id'),
        'status': request.args.get('status')})
    data, page = paginate(items, S.reservation)
    return ok(data, 200, page)


@bp.route('/reservations/<reservationId>', methods=['GET'])
def get_reservation(reservationId):
    uid, role = get_context()
    r = get_path_resource(db.reservations, reservationId,
                          'ERR_RESERVATION_NOT_FOUND')
    return ok(S.reservation(r))


@bp.route('/reservations/<reservationId>/release', methods=['POST'])
def release_reservation(reservationId):
    uid, role = get_context()
    require_role(role, ['Customer', 'InventoryClerk'])
    r = db.reservations.get(reservationId)
    if r is not None and role == 'Customer':
        line = db.order_lines.get(r['order_line_id'])
        o = db.orders.get(line['order_id']) if line else None
        if o is not None:
            own_or_403(o['customer_id'], uid, role)
    r = get_path_resource(db.reservations, reservationId,
                          'ERR_RESERVATION_NOT_FOUND')
    get_body()
    if r['status'] != 'HELD':
        raise ApiError('ERR_RESERVATION_NOT_HELD', 'Reservation is not HELD')
    touched = set()
    svc._release_held_reservation(r, touched)
    svc.cascade_demotions([r['order_line_id']], touched, zero_only=False)
    return ok(S.reservation(r))
