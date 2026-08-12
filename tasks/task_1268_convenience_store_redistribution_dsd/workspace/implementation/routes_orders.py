"""Purchase orders: draft creation, submission (pricing engine + credit gate),
cancellation, delivery confirmation, and order-line reads."""
from datetime import timedelta

from flask import Blueprint, request

from db import STORE, new_record, touch, public, logical_now, logical_now_iso
from errors import (
    ApiError, not_found, invalid_state, stale_version, validation, forbidden,
    ERR_TOBACCO_LICENSE_MISSING, ERR_TAX_STAMP_UNAVAILABLE,
    ERR_ORDER_CUTOFF_PASSED, ERR_PRODUCT_NOT_ON_GUIDE,
    ERR_SPLIT_CASE_NOT_ALLOWED, ERR_CREDIT_HOLD, ERR_CREDIT_LIMIT_EXCEEDED,
)
from middleware import (
    authenticate, require_role, check_store_ownership, parse_body,
    req_str, req_int, parse_pagination, list_page,
)
from response import ok_object, ok_list
from services import (
    order_lines, compute_pricing, tobacco_pack_count, tax_stamp_cost,
    find_stamp_supply, next_delivery_date, cutoff_instant,
    refresh_retailer, maybe_complete_manifest, TERMS_DAYS,
    MIN_DROP_THRESHOLD_CENTS, MIN_DROP_FEE_CENTS, parse_date,
)
from routes_retailers import get_retailer_or_404
from routes_catalog import get_guide_or_404, get_product_or_404

bp = Blueprint('orders', __name__)

ORDER_READ_ROLES = ('WholesaleAdmin', 'SalesRep', 'StoreManager', 'RouteDriver')


def get_order_or_404(oid):
    rec = STORE['purchase_orders'].get(oid)
    if rec is None:
        raise not_found('purchase order %s does not exist' % oid)
    return rec


def get_line_or_404(lid):
    rec = STORE['order_lines'].get(lid)
    if rec is None:
        raise not_found('order line %s does not exist' % lid)
    return rec


def order_has_tobacco(lines):
    for line in lines:
        if STORE['products'][line['product_id']]['is_tobacco']:
            return True
    return False


# ---------------------------------------------------------------- create draft

@bp.post('/purchase-orders')
def create_purchase_order():
    uid, role = authenticate()
    body = parse_body()
    retailer_id = req_str(body, 'retailer_id')
    order_guide_id = req_str(body, 'order_guide_id')
    raw_lines = body.get('lines')
    if not isinstance(raw_lines, list):
        raise validation("field 'lines' is missing or is not an array")
    parsed_lines = []
    for entry in raw_lines:
        if not isinstance(entry, dict):
            raise validation('each order line must be an object')
        pid = entry.get('product_id')
        cases = entry.get('cases_qty')
        splits = entry.get('split_units_qty')
        if not isinstance(pid, str):
            raise validation("order line 'product_id' must be a string")
        if isinstance(cases, bool) or not isinstance(cases, int) or cases < 0:
            raise validation("order line 'cases_qty' must be an integer >= 0")
        if isinstance(splits, bool) or not isinstance(splits, int) or splits < 0:
            raise validation("order line 'split_units_qty' must be an integer >= 0")
        parsed_lines.append({'product_id': pid, 'cases_qty': cases,
                             'split_units_qty': splits})

    require_role(role, ('StoreManager',))
    check_store_ownership(uid, role, retailer_id)

    retailer = get_retailer_or_404(retailer_id)
    guide = get_guide_or_404(order_guide_id)
    products = []
    for pl in parsed_lines:
        products.append(get_product_or_404(pl['product_id']))

    has_tobacco = any(p['is_tobacco'] for p in products)
    if has_tobacco and not retailer['tobacco_license_id']:
        raise ApiError(ERR_TOBACCO_LICENSE_MISSING, 422,
                       'tobacco order lines require the retailer tobacco_license_id')

    guide_product_ids = {l['product_id'] for l in guide['lines']}
    for pl in parsed_lines:
        if pl['product_id'] not in guide_product_ids:
            raise ApiError(ERR_PRODUCT_NOT_ON_GUIDE, 422,
                           'ordered product is absent from the order guide')
    for pl, product in zip(parsed_lines, products):
        if pl['split_units_qty'] > 0 and not product['split_case_allowed']:
            raise ApiError(ERR_SPLIT_CASE_NOT_ALLOWED, 422,
                           'split_units_qty > 0 on a product with split_case_allowed false')

    order = new_record()
    order.update({
        'retailer_id': retailer_id,
        'order_guide_id': order_guide_id,
        'manifest_id': None,
        'status': 'DRAFT',
        'has_tobacco': has_tobacco,
        'merch_subtotal_cents': 0,
        'promo_allowance_cents': 0,
        'pick_fee_cents': 0,
        'min_drop_fee_cents': 0,
        'fuel_surcharge_cents': 0,
        'tax_stamp_cost_cents': 0,
        'provisional_total_cents': 0,
        'final_total_cents': 0,
        'weight_lbs': 0,
        'submitted_at': None,
    })
    STORE['purchase_orders'][order['id']] = order
    for pl in parsed_lines:
        line = new_record(common=False)
        line.update({
            'order_id': order['id'],
            'product_id': pl['product_id'],
            'cases_qty': pl['cases_qty'],
            'split_units_qty': pl['split_units_qty'],
            'line_merch_cents': 0,
            'line_promo_cents': 0,
            'delivered_cases': 0,
            'delivered_split_units': 0,
        })
        STORE['order_lines'][line['id']] = line
    return ok_object(public(order), 201)


# -------------------------------------------------------------------- reads

@bp.get('/purchase-orders')
def list_purchase_orders():
    uid, role = authenticate()
    require_role(role, ORDER_READ_ROLES)
    limit, offset = parse_pagination()
    items = list(STORE['purchase_orders'].values())
    if role == 'StoreManager':
        requested = request.args.get('retailer_id')
        if requested is not None and requested != uid:
            raise forbidden('store manager may only list their own orders')
        items = [o for o in items if o['retailer_id'] == uid]
    for param in ('retailer_id', 'manifest_id', 'order_guide_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o.get(param) == v]
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/purchase-orders/<oid>')
def get_purchase_order(oid):
    uid, role = authenticate()
    require_role(role, ORDER_READ_ROLES)
    rec = get_order_or_404(oid)
    check_store_ownership(uid, role, rec['retailer_id'])
    return ok_object(public(rec))


@bp.get('/purchase-orders/<oid>/lines')
def list_order_lines(oid):
    uid, role = authenticate()
    require_role(role, ORDER_READ_ROLES)
    limit, offset = parse_pagination()
    order = get_order_or_404(oid)
    check_store_ownership(uid, role, order['retailer_id'])
    items = order_lines(oid)
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/order-lines')
def list_all_order_lines():
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin',))
    limit, offset = parse_pagination()
    items = list(STORE['order_lines'].values())
    for param in ('order_id', 'product_id'):
        v = request.args.get(param)
        if v is not None:
            items = [l for l in items if l.get(param) == v]
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/order-lines/<lid>')
def get_order_line(lid):
    uid, role = authenticate()
    require_role(role, ORDER_READ_ROLES)
    rec = get_line_or_404(lid)
    order = STORE['purchase_orders'].get(rec['order_id'])
    if role == 'StoreManager':
        check_store_ownership(uid, role, order['retailer_id'] if order else None)
    return ok_object(public(rec))


# -------------------------------------------------------------------- submit

@bp.post('/purchase-orders/<oid>/submit')
def submit_order(oid):
    uid, role = authenticate()
    body = parse_body()
    expected_version = req_int(body, 'expected_order_version')
    require_role(role, ('StoreManager',))
    order = get_order_or_404(oid)
    check_store_ownership(uid, role, order['retailer_id'])

    if order['status'] != 'DRAFT':
        raise invalid_state('only a DRAFT order may be submitted')
    if expected_version != order['version']:
        raise stale_version()

    retailer = STORE['retailers'][order['retailer_id']]
    guide = STORE['order_guides'][order['order_guide_id']]
    lines = order_lines(order['id'])

    # regulated-product safety
    supply = None
    if order['has_tobacco']:
        if not retailer['tobacco_license_id']:
            raise ApiError(ERR_TOBACCO_LICENSE_MISSING, 422,
                           'tobacco order lines require the retailer tobacco_license_id')
        supply = find_stamp_supply(retailer['jurisdiction_code'])
        if supply is None or supply['status'] != 'ACTIVE':
            raise ApiError(ERR_TAX_STAMP_UNAVAILABLE, 422,
                           'no ACTIVE tax stamp supply for the retailer jurisdiction')

    # temporal: submission must be before the guide cutoff
    now = logical_now()
    delivery_date = next_delivery_date(retailer['delivery_day'], now)
    cutoff = cutoff_instant(delivery_date, guide['cutoff_hours_before'])
    if not now < cutoff:
        raise ApiError(ERR_ORDER_CUTOFF_PASSED, 422,
                       'submission attempted after the order guide cutoff')

    # guide membership re-verified at submit
    guide_product_ids = {l['product_id'] for l in guide['lines']}
    for line in lines:
        if line['product_id'] not in guide_product_ids:
            raise ApiError(ERR_PRODUCT_NOT_ON_GUIDE, 422,
                           'ordered product is absent from the order guide')

    # fiscal gates: hold first, then limit
    if retailer['credit_status'] != 'GOOD_STANDING':
        raise ApiError(ERR_CREDIT_HOLD, 422,
                       'order submit blocked while retailer is on CREDIT_HOLD')

    pricing = compute_pricing(lines, delivery_date, delivered=False)
    merch = pricing['merch']
    promo = pricing['promo']
    pick = pricing['pick']
    weight = pricing['weight']
    net_merch = merch - promo
    min_drop_fee = MIN_DROP_FEE_CENTS if net_merch < MIN_DROP_THRESHOLD_CENTS else 0
    tax_stamp = 0
    if order['has_tobacco']:
        packs = tobacco_pack_count(lines, delivered=False)
        tax_stamp, _rolls = tax_stamp_cost(supply, packs)
    provisional = merch - promo + pick + min_drop_fee + tax_stamp

    if retailer['exposure_forward_cents'] + provisional > retailer['credit_limit_cents']:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 422,
                       'order would push exposure_forward_cents above credit_limit_cents')

    for line in lines:
        lv = pricing['line_values'][line['id']]
        line['line_merch_cents'] = lv['line_merch_cents']
        line['line_promo_cents'] = lv['line_promo_cents']
    order['merch_subtotal_cents'] = merch
    order['promo_allowance_cents'] = promo
    order['pick_fee_cents'] = pick
    order['min_drop_fee_cents'] = min_drop_fee
    order['tax_stamp_cost_cents'] = tax_stamp
    order['provisional_total_cents'] = provisional
    order['weight_lbs'] = weight
    order['submitted_at'] = logical_now_iso()
    order['status'] = 'SUBMITTED'
    touch(order)
    refresh_retailer(retailer)
    return ok_object(public(order))


# -------------------------------------------------------------------- cancel

@bp.post('/purchase-orders/<oid>/cancel')
def cancel_order(oid):
    uid, role = authenticate()
    parse_body()
    require_role(role, ('StoreManager',))
    order = get_order_or_404(oid)
    check_store_ownership(uid, role, order['retailer_id'])
    if order['status'] not in ('DRAFT', 'SUBMITTED'):
        raise invalid_state('only a DRAFT or SUBMITTED order may be cancelled')
    retailer = STORE['retailers'][order['retailer_id']]
    order['status'] = 'CANCELLED'
    touch(order)
    refresh_retailer(retailer)
    return ok_object(public(order))


# ---------------------------------------------------------- confirm delivery

@bp.post('/purchase-orders/<oid>/confirm-delivery')
def confirm_delivery(oid):
    uid, role = authenticate()
    parse_body()
    require_role(role, ('RouteDriver',))
    order = get_order_or_404(oid)
    if order['status'] != 'CLOSED':
        raise invalid_state('only a CLOSED order may be confirmed delivered')
    manifest = STORE['delivery_manifests'].get(order['manifest_id'])
    if manifest is None or manifest['status'] not in ('CLOSED', 'COMPLETED'):
        raise invalid_state('manifest is not CLOSED or COMPLETED')

    lines = order_lines(order['id'])
    # settle delivered quantities net of RECORDED/CREDITED exceptions
    for line in lines:
        short_cases = 0
        short_splits = 0
        for exc in STORE['delivery_exceptions'].values():
            if (exc['order_line_id'] == line['id']
                    and exc['status'] in ('RECORDED', 'CREDITED')):
                short_cases += exc['cases_qty']
                short_splits += exc['split_units_qty']
        line['delivered_cases'] = max(0, line['cases_qty'] - short_cases)
        line['delivered_split_units'] = max(0, line['split_units_qty'] - short_splits)

    delivery_date = parse_date(manifest['delivery_date'])
    pricing = compute_pricing(lines, delivery_date, delivered=True)
    for line in lines:
        lv = pricing['line_values'][line['id']]
        line['line_merch_cents'] = lv['line_merch_cents']
        line['line_promo_cents'] = lv['line_promo_cents']

    final_total = (pricing['merch'] - pricing['promo'] + pricing['pick']
                   + order['tax_stamp_cost_cents'] + order['fuel_surcharge_cents'])
    order['merch_subtotal_cents'] = pricing['merch']
    order['promo_allowance_cents'] = pricing['promo']
    order['pick_fee_cents'] = pricing['pick']
    order['final_total_cents'] = final_total
    order['status'] = 'DELIVERED'
    touch(order)

    # issue the invoice
    retailer = STORE['retailers'][order['retailer_id']]
    due = delivery_date + timedelta(days=TERMS_DAYS[retailer['credit_terms']])
    invoice = new_record()
    invoice.update({
        'order_id': order['id'],
        'retailer_id': retailer['id'],
        'invoiced_total_cents': final_total,
        'balance_cents': final_total,
        'due_date': due.isoformat(),
        'status': 'OPEN',
    })
    STORE['invoices'][invoice['id']] = invoice

    # auto-transition DELIVERED -> INVOICED once the invoice row is persisted
    order['status'] = 'INVOICED'
    touch(order)
    refresh_retailer(retailer)
    maybe_complete_manifest(manifest)
    return ok_object(public(invoice))
