"""Item master (products), order guides, promo events, retail price records."""
from flask import Blueprint, request

from db import STORE, new_record, touch, public
from errors import (
    ApiError, not_found, validation,
    ERR_DUPLICATE_SKU, ERR_PROMO_WINDOW_OVERLAP, ERR_GUIDE_DAY_MISMATCH,
)
from middleware import (
    authenticate, require_role, check_store_ownership, parse_body,
    req_str, opt_str, req_int, req_bool, opt_bool, req_enum, req_num,
    req_date, opt_date, parse_query_bool, parse_pagination, list_page,
    parse_date_str,
)
from response import ok_object, ok_list
from services import promo_status
from routes_retailers import get_retailer_or_404, DELIVERY_DAYS

bp = Blueprint('catalog', __name__)

PROMO_TYPES = ('OFF_INVOICE', 'SCAN_BACK')
PRICE_STATUSES = ('ACTIVE', 'SUPERSEDED')


def get_product_or_404(pid):
    rec = STORE['products'].get(pid)
    if rec is None:
        raise not_found('product %s does not exist' % pid)
    return rec


def get_guide_or_404(gid):
    rec = STORE['order_guides'].get(gid)
    if rec is None:
        raise not_found('order guide %s does not exist' % gid)
    return rec


def promo_public(p):
    d = public(p)
    d['status'] = promo_status(p)
    return d


# ------------------------------------------------------------------- products

@bp.post('/products')
def create_product():
    uid, role = authenticate()
    body = parse_body()
    sku = req_str(body, 'sku')
    description = req_str(body, 'description')
    case_pack_units = req_int(body, 'case_pack_units', minimum=1)
    case_cost_cents = req_int(body, 'case_cost_cents')
    unit_cost_cents = req_int(body, 'unit_cost_cents')
    split_case_allowed = req_bool(body, 'split_case_allowed')
    is_tobacco = opt_bool(body, 'is_tobacco', default=False)
    weight = req_num(body, 'weight_lbs_per_case')
    require_role(role, ('WholesaleAdmin',))

    for p in STORE['products'].values():
        if p['sku'] == sku:
            raise ApiError(ERR_DUPLICATE_SKU, 409, 'product sku already exists')

    rec = new_record()
    rec.update({
        'sku': sku,
        'description': description,
        'case_pack_units': case_pack_units,
        'case_cost_cents': case_cost_cents,
        'unit_cost_cents': unit_cost_cents,
        'split_case_allowed': split_case_allowed,
        'is_tobacco': is_tobacco,
        'weight_lbs_per_case': weight,
        'status': 'ACTIVE',
    })
    STORE['products'][rec['id']] = rec
    return ok_object(public(rec), 201)


@bp.get('/products')
def list_products():
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'SalesRep', 'StoreManager'))
    limit, offset = parse_pagination()
    items = list(STORE['products'].values())
    status = request.args.get('status')
    is_tobacco = request.args.get('is_tobacco')
    if status is not None:
        items = [p for p in items if p['status'] == status]
    if is_tobacco is not None:
        want = parse_query_bool(is_tobacco, 'is_tobacco')
        items = [p for p in items if p['is_tobacco'] == want]
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/products/<pid>')
def get_product(pid):
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'SalesRep', 'StoreManager'))
    rec = get_product_or_404(pid)
    return ok_object(public(rec))


# --------------------------------------------------------------- order guides

@bp.post('/order-guides')
def create_order_guide():
    uid, role = authenticate()
    body = parse_body()
    retailer_id = req_str(body, 'retailer_id')
    delivery_day = req_enum(body, 'delivery_day', DELIVERY_DAYS)
    cutoff_hours_before = req_int(body, 'cutoff_hours_before', minimum=0)
    lines_raw = req_raw_lines(body)
    require_role(role, ('SalesRep',))

    retailer = get_retailer_or_404(retailer_id)
    lines = []
    for entry in lines_raw:
        if not isinstance(entry, dict):
            raise validation('each guide line must be an object')
        pid = entry.get('product_id')
        par = entry.get('par_cases')
        if not isinstance(pid, str):
            raise validation("guide line 'product_id' must be a string")
        if isinstance(par, bool) or not isinstance(par, int) or par < 0:
            raise validation("guide line 'par_cases' must be an integer >= 0")
        get_product_or_404(pid)
        lines.append({'product_id': pid, 'par_cases': par})

    if delivery_day != retailer['delivery_day']:
        raise ApiError(ERR_GUIDE_DAY_MISMATCH, 422,
                       'order guide delivery_day does not match retailer delivery_day')

    rec = new_record()
    rec.update({
        'retailer_id': retailer_id,
        'delivery_day': delivery_day,
        'cutoff_hours_before': cutoff_hours_before,
        'lines': lines,
        'status': 'ACTIVE',
    })
    STORE['order_guides'][rec['id']] = rec
    return ok_object(public(rec), 201)


def req_raw_lines(body):
    lines = body.get('lines')
    if lines is None or not isinstance(lines, list):
        raise validation("field 'lines' is missing or is not an array")
    return lines


@bp.get('/order-guides/<gid>')
def get_order_guide(gid):
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'SalesRep', 'StoreManager'))
    rec = get_guide_or_404(gid)
    check_store_ownership(uid, role, rec['retailer_id'])
    return ok_object(public(rec))


# --------------------------------------------------------------- promo events

@bp.post('/promo-events')
def create_promo_event():
    uid, role = authenticate()
    body = parse_body()
    product_id = req_str(body, 'product_id')
    promo_type = req_enum(body, 'promo_type', PROMO_TYPES)
    discount = req_int(body, 'discount_pct_bps', minimum=1, maximum=10000)
    start_date = req_date(body, 'start_date')
    end_date = req_date(body, 'end_date')
    if parse_date_str(end_date, 'end_date') < parse_date_str(start_date, 'start_date'):
        raise validation('end_date must be on or after start_date')
    require_role(role, ('SalesRep',))

    get_product_or_404(product_id)
    for p in STORE['promo_events'].values():
        if p['product_id'] != product_id:
            continue
        # closed inclusive intervals: overlap iff start <= other_end and other_start <= end
        if start_date <= p['end_date'] and p['start_date'] <= end_date:
            raise ApiError(ERR_PROMO_WINDOW_OVERLAP, 409,
                           'promo window overlaps an existing promo for this product')

    rec = new_record()
    rec.update({
        'product_id': product_id,
        'promo_type': promo_type,
        'discount_pct_bps': discount,
        'start_date': start_date,
        'end_date': end_date,
        'status': 'SCHEDULED',
    })
    STORE['promo_events'][rec['id']] = rec
    return ok_object(promo_public(rec), 201)


@bp.get('/promo-events')
def list_promo_events():
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'SalesRep', 'StoreManager'))
    limit, offset = parse_pagination()
    items = list(STORE['promo_events'].values())
    product_id = request.args.get('product_id')
    status = request.args.get('status')
    if product_id is not None:
        items = [p for p in items if p['product_id'] == product_id]
    if status is not None:
        items = [p for p in items if promo_status(p) == status]
    page, total = list_page(items, promo_public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/promo-events/<pid>')
def get_promo_event(pid):
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'SalesRep', 'StoreManager'))
    rec = STORE['promo_events'].get(pid)
    if rec is None:
        raise not_found('promo event %s does not exist' % pid)
    return ok_object(promo_public(rec))


# --------------------------------------------------------- retail price records

def _publish_price_record(retailer_id, product_id, shelf_price_cents,
                          effective_start, effective_end):
    prior = None
    for r in STORE['retail_price_records'].values():
        if (r['retailer_id'] == retailer_id and r['product_id'] == product_id
                and r['status'] == 'ACTIVE'):
            prior = r
            break
    if prior is not None:
        prior['status'] = 'SUPERSEDED'
        touch(prior)
    rec = new_record()
    rec.update({
        'retailer_id': retailer_id,
        'product_id': product_id,
        'shelf_price_cents': shelf_price_cents,
        'effective_start': effective_start,
        'effective_end': effective_end,
        'supersedes_id': prior['id'] if prior is not None else None,
        'status': 'ACTIVE',
    })
    STORE['retail_price_records'][rec['id']] = rec
    return rec


@bp.post('/retail-price-records')
def create_price_record():
    uid, role = authenticate()
    body = parse_body()
    retailer_id = req_str(body, 'retailer_id')
    product_id = req_str(body, 'product_id')
    shelf_price_cents = req_int(body, 'shelf_price_cents')
    effective_start = req_date(body, 'effective_start')
    effective_end = opt_date(body, 'effective_end')
    require_role(role, ('SalesRep',))

    get_retailer_or_404(retailer_id)
    get_product_or_404(product_id)
    rec = _publish_price_record(retailer_id, product_id, shelf_price_cents,
                                effective_start, effective_end)
    return ok_object(public(rec), 201)


@bp.get('/retail-price-records')
def list_price_records():
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'SalesRep'))
    limit, offset = parse_pagination()
    items = list(STORE['retail_price_records'].values())
    for param in ('retailer_id', 'product_id', 'supersedes_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    page, total = list_page(items, public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/retail-price-records/<rid>')
def get_price_record(rid):
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'SalesRep'))
    rec = STORE['retail_price_records'].get(rid)
    if rec is None:
        raise not_found('retail price record %s does not exist' % rid)
    return ok_object(public(rec))
