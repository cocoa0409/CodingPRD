"""Delivery manifests: creation, begin-loading, assign-order, close, and
door delivery exceptions (shorts/damages)."""
from decimal import Decimal

from flask import Blueprint, request

from db import STORE, new_record, touch, public
from errors import (
    ApiError, not_found, invalid_state, stale_version,
    ERR_MANIFEST_NOT_OPEN, ERR_MANIFEST_OVERWEIGHT,
)
from middleware import (
    authenticate, require_role, parse_body, req_str, req_int, req_num,
    req_date, req_enum, parse_pagination, list_page,
)
from response import ok_object, ok_list
from services import (
    order_lines, tobacco_pack_count, tax_stamp_cost, find_stamp_supply,
    find_fuel_rate_for_date, fuel_tier_rate, round_half_up_cents,
    refresh_retailer,
)

bp = Blueprint('manifests', __name__)

MANIFEST_READ_ROLES = ('WholesaleAdmin', 'RouteDriver')
EXCEPTION_READ_ROLES = ('WholesaleAdmin', 'RouteDriver', 'CreditManager')
EXCEPTION_TYPES = ('SHORT', 'DAMAGE')


def get_manifest_or_404(mid):
    rec = STORE['delivery_manifests'].get(mid)
    if rec is None:
        raise not_found('delivery manifest %s does not exist' % mid)
    return rec


@bp.post('/delivery-manifests')
def create_manifest():
    uid, role = authenticate()
    body = parse_body()
    route_code = req_str(body, 'route_code')
    delivery_date = req_date(body, 'delivery_date')
    capacity_lbs = req_num(body, 'capacity_lbs')
    require_role(role, ('WholesaleAdmin',))

    rec = new_record()
    rec.update({
        'route_code': route_code,
        'delivery_date': delivery_date,
        'status': 'SCHEDULED',
        'capacity_lbs': capacity_lbs,
        'total_weight_lbs': 0,
        'overweight_flag': False,
        'fuel_rate_id': None,
    })
    STORE['delivery_manifests'][rec['id']] = rec
    return ok_object(public(rec), 201)


@bp.get('/delivery-manifests')
def list_manifests():
    uid, role = authenticate()
    require_role(role, MANIFEST_READ_ROLES)
    limit, offset = parse_pagination()
    items = list(STORE['delivery_manifests'].values())
    for param in ('route_code', 'delivery_date', 'fuel_rate_id'):
        v = request.args.get(param)
        if v is not None:
            items = [m for m in items if m.get(param) == v]
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/delivery-manifests/<mid>')
def get_manifest(mid):
    uid, role = authenticate()
    require_role(role, MANIFEST_READ_ROLES)
    rec = get_manifest_or_404(mid)
    return ok_object(public(rec))


@bp.post('/delivery-manifests/<mid>/begin-loading')
def begin_loading(mid):
    uid, role = authenticate()
    parse_body()
    require_role(role, ('WholesaleAdmin',))
    manifest = get_manifest_or_404(mid)
    if manifest['status'] != 'SCHEDULED':
        raise invalid_state('manifest must be SCHEDULED to begin loading')
    manifest['status'] = 'LOADING'
    touch(manifest)
    return ok_object(public(manifest))


@bp.post('/delivery-manifests/<mid>/assign-order')
def assign_order(mid):
    uid, role = authenticate()
    body = parse_body()
    order_id = req_str(body, 'order_id')
    expected_version = req_int(body, 'expected_manifest_version')
    require_role(role, ('WholesaleAdmin',))
    manifest = get_manifest_or_404(mid)
    order = STORE['purchase_orders'].get(order_id)
    if order is None:
        raise not_found('purchase order %s does not exist' % order_id)

    if order['status'] != 'SUBMITTED':
        raise invalid_state('only a SUBMITTED order may be assigned to a manifest')
    if manifest['status'] not in ('SCHEDULED', 'LOADING'):
        raise ApiError(ERR_MANIFEST_NOT_OPEN, 409,
                       'manifest is not open for order assignment')
    if expected_version != manifest['version']:
        raise stale_version()
    if manifest['overweight_flag']:
        raise ApiError(ERR_MANIFEST_OVERWEIGHT, 422,
                       'manifest is over weight capacity; further assigns blocked')

    order['manifest_id'] = manifest['id']
    order['status'] = 'ASSIGNED'
    touch(order)
    manifest['total_weight_lbs'] = manifest['total_weight_lbs'] + order['weight_lbs']
    if manifest['total_weight_lbs'] > manifest['capacity_lbs']:
        manifest['overweight_flag'] = True
    touch(manifest)
    return ok_object(public(order))


@bp.post('/delivery-manifests/<mid>/close')
def close_manifest(mid):
    uid, role = authenticate()
    body = parse_body()
    expected_version = req_int(body, 'expected_manifest_version')
    require_role(role, ('WholesaleAdmin',))
    manifest = get_manifest_or_404(mid)
    if manifest['status'] != 'LOADING':
        raise invalid_state('manifest must be LOADING to close')
    if expected_version != manifest['version']:
        raise stale_version()

    # lock the fuel rate of the delivery week and stamp every ASSIGNED order
    rate = find_fuel_rate_for_date(manifest['delivery_date'])
    manifest['fuel_rate_id'] = rate['id'] if rate is not None else None
    tier = fuel_tier_rate(rate['doe_index_usd']) if rate is not None else Decimal('0')

    assigned = [o for o in STORE['purchase_orders'].values()
                if o.get('manifest_id') == manifest['id'] and o['status'] == 'ASSIGNED']
    for order in assigned:
        surcharge_base = (order['merch_subtotal_cents']
                          - order['promo_allowance_cents']
                          + order['pick_fee_cents'])
        order['fuel_surcharge_cents'] = round_half_up_cents(
            Decimal(surcharge_base) * tier)
        order['status'] = 'CLOSED'
        touch(order)
        if order['has_tobacco']:
            retailer = STORE['retailers'][order['retailer_id']]
            supply = find_stamp_supply(retailer['jurisdiction_code'])
            if supply is not None:
                lines = order_lines(order['id'])
                packs = tobacco_pack_count(lines, delivered=False)
                _cost, rolls = tax_stamp_cost(supply, packs)
                supply['rolls_on_hand'] = supply['rolls_on_hand'] - rolls
                touch(supply)
    manifest['status'] = 'CLOSED'
    touch(manifest)
    return ok_object(public(manifest))


# --------------------------------------------------------- delivery exceptions

@bp.post('/delivery-manifests/<mid>/delivery-exceptions')
def create_delivery_exception(mid):
    uid, role = authenticate()
    body = parse_body()
    order_id = req_str(body, 'order_id')
    order_line_id = req_str(body, 'order_line_id')
    exception_type = req_enum(body, 'exception_type', EXCEPTION_TYPES)
    cases_qty = req_int(body, 'cases_qty', minimum=0)
    split_units_qty = req_int(body, 'split_units_qty', minimum=0)
    require_role(role, ('RouteDriver',))

    manifest = get_manifest_or_404(mid)
    order = STORE['purchase_orders'].get(order_id)
    if order is None:
        raise not_found('purchase order %s does not exist' % order_id)
    line = STORE['order_lines'].get(order_line_id)
    if line is None or line['order_id'] != order['id']:
        raise not_found('order line %s does not exist' % order_line_id)
    if order.get('manifest_id') != manifest['id']:
        raise not_found('order %s is not part of manifest %s' % (order_id, mid))

    product = STORE['products'][line['product_id']]
    credit_amount = (cases_qty * product['case_cost_cents']
                     + split_units_qty * product['unit_cost_cents'])

    exc = new_record()
    exc.update({
        'manifest_id': manifest['id'],
        'order_id': order['id'],
        'order_line_id': line['id'],
        'exception_type': exception_type,
        'cases_qty': cases_qty,
        'split_units_qty': split_units_qty,
        'credit_amount_cents': credit_amount,
        'status': 'RECORDED',
    })
    STORE['delivery_exceptions'][exc['id']] = exc

    # when the order's invoice already exists, auto-create and post a credit memo
    invoice = None
    for inv in STORE['invoices'].values():
        if inv['order_id'] == order['id']:
            invoice = inv
            break
    if invoice is not None:
        memo = new_record()
        memo.update({
            'invoice_id': invoice['id'],
            'exception_id': exc['id'],
            'origin': exception_type,
            'amount_cents': credit_amount,
            'status': 'POSTED',
        })
        STORE['credit_memos'][memo['id']] = memo
        invoice['balance_cents'] = invoice['balance_cents'] - credit_amount
        if invoice['balance_cents'] <= 0:
            invoice['status'] = 'PAID'
        touch(invoice)
        retailer = STORE['retailers'][invoice['retailer_id']]
        refresh_retailer(retailer)
        exc['status'] = 'CREDITED'

    return ok_object(public(exc), 201)


@bp.get('/delivery-exceptions')
def list_delivery_exceptions():
    uid, role = authenticate()
    require_role(role, EXCEPTION_READ_ROLES)
    limit, offset = parse_pagination()
    items = list(STORE['delivery_exceptions'].values())
    for param in ('manifest_id', 'order_id', 'order_line_id'):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e.get(param) == v]
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/delivery-exceptions/<eid>')
def get_delivery_exception(eid):
    uid, role = authenticate()
    require_role(role, EXCEPTION_READ_ROLES)
    rec = STORE['delivery_exceptions'].get(eid)
    if rec is None:
        raise not_found('delivery exception %s does not exist' % eid)
    return ok_object(public(rec))
