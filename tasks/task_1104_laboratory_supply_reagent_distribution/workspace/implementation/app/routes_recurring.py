"""Standing orders, consignment agreements, consumption records."""
from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, request

from .db import db, new_id, fmt_wall, now_wall
from .errors import ApiError
from .response import ok
from . import serializers as S
from . import services as svc
from .validators import (
    get_context, require_role, get_body, check_unknown, as_str, as_int,
    as_number, as_date, get_path_resource, check_body_id, id_or_none,
    paginate, apply_filters,
)

bp = Blueprint('recurring', __name__)
WINDOW_BUFFER_DAYS = 7


def own_or_403(customer_id, uid, role):
    if role == 'Customer' and customer_id != uid:
        raise ApiError('ERR_RESOURCE_OWNERSHIP_VIOLATION',
                       'Resource belongs to a different customer')


# ----------------------------------------------------------- standing orders

@bp.route('/standing-orders', methods=['POST'])
def create_standing_order():
    uid, role = get_context()
    require_role(role, ['Customer'])
    body = get_body()
    cid = id_or_none(body, 'customer_id')
    if cid is not None and cid != uid:
        raise ApiError('ERR_RESOURCE_OWNERSHIP_VIOLATION',
                       'customer_id must equal X-User-ID')
    check_body_id(db.customers, body, 'customer_id', 'ERR_CUSTOMER_NOT_FOUND')
    check_body_id(db.products, body, 'product_id', 'ERR_PRODUCT_NOT_FOUND')
    check_body_id(db.warehouses, body, 'warehouse_id', 'ERR_WAREHOUSE_NOT_FOUND')
    check_unknown(body, ['customer_id', 'product_id', 'warehouse_id',
                         'quantity_per_run', 'interval_days', 'effective_from',
                         'effective_until'])
    customer_id = as_str(body, 'customer_id')
    product_id = as_str(body, 'product_id')
    warehouse_id = as_str(body, 'warehouse_id')
    qty = as_int(body, 'quantity_per_run', min_value=1)
    interval = as_int(body, 'interval_days', min_value=1)
    eff_from = as_date(body, 'effective_from')
    eff_until = as_date(body, 'effective_until')
    if date.fromisoformat(eff_until) < date.fromisoformat(eff_from):
        raise ApiError('ERR_INVALID_REQUEST',
                       'effective_until must not precede effective_from')
    # standing_order_window_buffer: clear every existing window by >= 7 days
    nf, nu = date.fromisoformat(eff_from), date.fromisoformat(eff_until)
    for so in db.standing_orders.values():
        if so['customer_id'] != customer_id or so['product_id'] != product_id:
            continue
        if so['status'] not in ('ACTIVE', 'PAUSED'):
            continue
        ef, eu = date.fromisoformat(so['effective_from']), \
            date.fromisoformat(so['effective_until'])
        if nf >= eu + timedelta(days=WINDOW_BUFFER_DAYS) \
                or nu <= ef - timedelta(days=WINDOW_BUFFER_DAYS):
            continue
        raise ApiError('ERR_STANDING_ORDER_WINDOW_CONFLICT',
                       'Window fails the 7-day buffer against an existing '
                       'standing order')
    so = db.new_common()
    so.update({'customer_id': customer_id, 'product_id': product_id,
               'warehouse_id': warehouse_id, 'quantity_per_run': qty,
               'interval_days': interval, 'effective_from': eff_from,
               'effective_until': eff_until, 'next_run_date': eff_from,
               'generated_order_count': 0, 'status': 'ACTIVE'})
    db.standing_orders[so['id']] = so
    return ok(S.standing_order(so), 201)


def so_visible_or_404(soid, uid, role):
    so = db.standing_orders.get(soid)
    if so is not None:
        own_or_403(so['customer_id'], uid, role)
    return get_path_resource(db.standing_orders, soid,
                             'ERR_STANDING_ORDER_NOT_FOUND')


@bp.route('/standing-orders', methods=['GET'])
def list_standing_orders():
    uid, role = get_context()
    items = sorted(db.standing_orders.values(), key=lambda x: x['_seq'])
    if role == 'Customer':
        items = [s for s in items if s['customer_id'] == uid]
    items = apply_filters(items, {
        'customer_id': request.args.get('customer_id'),
        'product_id': request.args.get('product_id'),
        'warehouse_id': request.args.get('warehouse_id'),
        'status': request.args.get('status')})
    data, page = paginate(items, S.standing_order)
    return ok(data, 200, page)


@bp.route('/standing-orders/<standingOrderId>', methods=['GET'])
def get_standing_order(standingOrderId):
    uid, role = get_context()
    so = so_visible_or_404(standingOrderId, uid, role)
    return ok(S.standing_order(so))


@bp.route('/standing-orders/<standingOrderId>/pause', methods=['POST'])
def pause_standing_order(standingOrderId):
    uid, role = get_context()
    require_role(role, ['Customer'])
    so = so_visible_or_404(standingOrderId, uid, role)
    get_body()
    if so['status'] != 'ACTIVE':
        raise ApiError('ERR_STANDING_ORDER_NOT_ACTIVE',
                       'Standing order is not ACTIVE')
    so['status'] = 'PAUSED'
    db.touch('standing_orders', so['id'], set())
    return ok(S.standing_order(so))


@bp.route('/standing-orders/<standingOrderId>/resume', methods=['POST'])
def resume_standing_order(standingOrderId):
    uid, role = get_context()
    require_role(role, ['Customer'])
    so = so_visible_or_404(standingOrderId, uid, role)
    get_body()
    if so['status'] != 'PAUSED':
        raise ApiError('ERR_STANDING_ORDER_NOT_PAUSED',
                       'Standing order is not PAUSED')
    so['status'] = 'ACTIVE'
    db.touch('standing_orders', so['id'], set())
    return ok(S.standing_order(so))


@bp.route('/standing-orders/<standingOrderId>/cancel', methods=['POST'])
def cancel_standing_order(standingOrderId):
    uid, role = get_context()
    require_role(role, ['Customer'])
    so = so_visible_or_404(standingOrderId, uid, role)
    get_body()
    if so['status'] not in ('ACTIVE', 'PAUSED'):
        raise ApiError('ERR_STANDING_ORDER_TERMINAL',
                       'Standing order is already CANCELLED')
    so['status'] = 'CANCELLED'
    db.touch('standing_orders', so['id'], set())
    return ok(S.standing_order(so))


# ----------------------------------------------------------- consignment

@bp.route('/consignment-agreements', methods=['POST'])
def create_agreement():
    uid, role = get_context()
    require_role(role, ['AccountManager'])
    body = get_body()
    check_body_id(db.customers, body, 'customer_id', 'ERR_CUSTOMER_NOT_FOUND')
    check_body_id(db.products, body, 'product_id', 'ERR_PRODUCT_NOT_FOUND')
    check_body_id(db.warehouses, body, 'replenishment_warehouse_id',
                  'ERR_WAREHOUSE_NOT_FOUND')
    check_unknown(body, ['customer_id', 'product_id', 'ceiling_quantity',
                         'reorder_point', 'contract_unit_price_cents',
                         'discount_pct', 'replenishment_warehouse_id',
                         'initial_stocked_quantity', 'effective_from',
                         'effective_until'])
    customer_id = as_str(body, 'customer_id')
    product_id = as_str(body, 'product_id')
    ceiling = as_int(body, 'ceiling_quantity', min_value=1)
    reorder = as_int(body, 'reorder_point', min_value=0)
    price = as_int(body, 'contract_unit_price_cents', min_value=1)
    discount = as_number(body, 'discount_pct', required=False, default=0,
                         min_value=0, max_value=0.5)
    repl_wh = as_str(body, 'replenishment_warehouse_id')
    initial = as_int(body, 'initial_stocked_quantity', required=False,
                     default=0, min_value=0)
    eff_from = as_date(body, 'effective_from')
    eff_until = as_date(body, 'effective_until')
    if initial > ceiling:
        raise ApiError('ERR_INVALID_REQUEST',
                       'initial_stocked_quantity may not exceed ceiling_quantity')
    if not date.fromisoformat(eff_until) > date.fromisoformat(eff_from):
        raise ApiError('ERR_INVALID_REQUEST',
                       'effective_until must be after effective_from')
    # consignment_window_overlap: half-open [from, until) overlap test
    nf, nu = date.fromisoformat(eff_from), date.fromisoformat(eff_until)
    for a in db.agreements.values():
        if a['customer_id'] != customer_id or a['product_id'] != product_id:
            continue
        if a['status'] not in ('ACTIVE', 'SUSPENDED'):
            continue
        ef, eu = date.fromisoformat(a['effective_from']), \
            date.fromisoformat(a['effective_until'])
        if ef < nu and nf < eu:
            raise ApiError('ERR_CONSIGNMENT_WINDOW_OVERLAP',
                           'Window overlaps an existing agreement')
    a = db.new_common()
    a.update({'customer_id': customer_id, 'product_id': product_id,
              'ceiling_quantity': ceiling, 'stocked_quantity': initial,
              'consumed_quantity': 0, 'reorder_point': reorder,
              'contract_unit_price_cents': price, 'discount_pct': discount,
              'replenishment_warehouse_id': repl_wh,
              'initial_stocked_quantity': initial,
              'effective_from': eff_from, 'effective_until': eff_until,
              'status': 'ACTIVE'})
    db.agreements[a['id']] = a
    return ok(S.agreement(a), 201)


def agreement_visible_or_404(aid, uid, role):
    a = db.agreements.get(aid)
    if a is not None:
        own_or_403(a['customer_id'], uid, role)
    return get_path_resource(db.agreements, aid,
                             'ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND')


@bp.route('/consignment-agreements', methods=['GET'])
def list_agreements():
    uid, role = get_context()
    items = sorted(db.agreements.values(), key=lambda x: x['_seq'])
    if role == 'Customer':
        items = [a for a in items if a['customer_id'] == uid]
    items = apply_filters(items, {
        'customer_id': request.args.get('customer_id'),
        'product_id': request.args.get('product_id'),
        'replenishment_warehouse_id': request.args.get(
            'replenishment_warehouse_id'),
        'status': request.args.get('status')})
    data, page = paginate(items, S.agreement)
    return ok(data, 200, page)


@bp.route('/consignment-agreements/<agreementId>', methods=['GET'])
def get_agreement(agreementId):
    uid, role = get_context()
    a = agreement_visible_or_404(agreementId, uid, role)
    return ok(S.agreement(a))


@bp.route('/consignment-agreements/<agreementId>/suspend', methods=['POST'])
def suspend_agreement(agreementId):
    uid, role = get_context()
    require_role(role, ['AccountManager'])
    a = get_path_resource(db.agreements, agreementId,
                          'ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND')
    get_body()
    if a['status'] != 'ACTIVE':
        raise ApiError('ERR_AGREEMENT_NOT_ACTIVE', 'Agreement is not ACTIVE')
    a['status'] = 'SUSPENDED'
    db.touch('agreements', a['id'], set())
    return ok(S.agreement(a))


@bp.route('/consignment-agreements/<agreementId>/reactivate', methods=['POST'])
def reactivate_agreement(agreementId):
    uid, role = get_context()
    require_role(role, ['AccountManager'])
    a = get_path_resource(db.agreements, agreementId,
                          'ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND')
    get_body()
    if a['status'] != 'SUSPENDED':
        raise ApiError('ERR_AGREEMENT_NOT_SUSPENDED',
                       'Agreement is not SUSPENDED')
    a['status'] = 'ACTIVE'
    db.touch('agreements', a['id'], set())
    return ok(S.agreement(a))


@bp.route('/consignment-agreements/<agreementId>/close', methods=['POST'])
def close_agreement(agreementId):
    uid, role = get_context()
    require_role(role, ['AccountManager'])
    a = get_path_resource(db.agreements, agreementId,
                          'ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND')
    get_body()
    if a['status'] not in ('ACTIVE', 'SUSPENDED'):
        raise ApiError('ERR_AGREEMENT_ALREADY_CLOSED',
                       'Agreement is already CLOSED')
    a['status'] = 'CLOSED'
    db.touch('agreements', a['id'], set())
    return ok(S.agreement(a))


@bp.route('/consignment-agreements/<agreementId>/consumption', methods=['POST'])
def record_consumption(agreementId):
    uid, role = get_context()
    require_role(role, ['Customer', 'AccountManager'])
    a = db.agreements.get(agreementId)
    if a is not None and role == 'Customer':
        own_or_403(a['customer_id'], uid, role)
    a = get_path_resource(db.agreements, agreementId,
                          'ERR_CONSIGNMENT_AGREEMENT_NOT_FOUND')
    body = get_body()
    check_unknown(body, ['quantity'])
    qty = as_int(body, 'quantity', min_value=1)
    if a['status'] != 'ACTIVE':
        raise ApiError('ERR_AGREEMENT_NOT_ACTIVE', 'Agreement is not ACTIVE')
    # business checks in order: recall, ceiling, on-hand
    if svc.issued_recall_for_product(a['product_id']):
        raise ApiError('ERR_PRODUCT_UNDER_RECALL',
                       'Product is covered by an issued recall')
    if a['consumed_quantity'] + qty > a['ceiling_quantity']:
        raise ApiError('ERR_CONSIGNMENT_CEILING_EXCEEDED',
                       'Consumption would exceed the agreement ceiling')
    on_hand = a['stocked_quantity'] - a['consumed_quantity']
    if qty > on_hand:
        raise ApiError('ERR_CONSUMPTION_EXCEEDS_STOCK',
                       'Consumption exceeds on-hand at customer')
    touched = set()
    charge = svc.rhu(Decimal(qty) * Decimal(a['contract_unit_price_cents'])
                     * (Decimal('1') - Decimal(str(a['discount_pct']))))
    r = {'id': new_id(), 'created_at': fmt_wall(now_wall()),
         '_seq': db.next_creation_seq(),
         'agreement_id': a['id'], 'quantity': qty,
         'unit_price_cents': a['contract_unit_price_cents'],
         'charge_cents': charge, '_recorded_dt': db.clock}
    db.consumption_records[r['id']] = r
    a['consumed_quantity'] += qty
    db.touch('agreements', a['id'], touched)
    db.touch('customers', a['customer_id'], touched)  # charge posts
    # consignment_replenishment: on-hand at or below reorder point triggers
    new_on_hand = a['stocked_quantity'] - a['consumed_quantity']
    if new_on_hand <= a['reorder_point'] and a['status'] == 'ACTIVE':
        order = svc.create_order_record(
            a['customer_id'], a['replenishment_warehouse_id'], 'STANDARD',
            (svc.logical_date() + timedelta(days=1)).isoformat(),
            [{'product_id': a['product_id'],
              'quantity': a['ceiling_quantity'] - new_on_hand,
              'fulfillment_mode': 'ANY'}])
        try:
            svc.submit_order(order, touched)
        except ApiError:
            pass  # standing-order style: failed auto-submit stays DRAFT
    return ok(S.consumption_record(r), 201)


@bp.route('/consumption-records', methods=['GET'])
def list_consumption_records():
    uid, role = get_context()
    items = sorted(db.consumption_records.values(), key=lambda x: x['_seq'])
    items = apply_filters(items, {'agreement_id': request.args.get('agreement_id')})
    data, page = paginate(items, S.consumption_record)
    return ok(data, 200, page)


@bp.route('/consumption-records/<recordId>', methods=['GET'])
def get_consumption_record(recordId):
    uid, role = get_context()
    r = get_path_resource(db.consumption_records, recordId,
                          'ERR_CONSUMPTION_RECORD_NOT_FOUND')
    return ok(S.consumption_record(r))
