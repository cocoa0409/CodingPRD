"""Retailer account, credit posture, credit hold, and per-retailer listings."""
from flask import Blueprint, request

from db import STORE, new_record, public
from errors import not_found
from middleware import (
    authenticate, require_role, check_store_ownership, parse_body,
    req_str, req_int, req_enum, opt_str, opt_int, opt_enum, req_bool,
    parse_pagination, list_page,
)
from response import ok_object, ok_list
from services import refresh_retailer, credit_summary

bp = Blueprint('retailers', __name__)

JURISDICTIONS = ('CA_NORTH', 'CA_SOUTH', 'NV_CLARK', 'AZ_MARICOPA')
CREDIT_TERMS = ('COD', 'NET7', 'NET14')
DELIVERY_DAYS = ('MON', 'TUE', 'WED', 'THU', 'FRI')


def get_retailer_or_404(rid):
    rec = STORE['retailers'].get(rid)
    if rec is None:
        raise not_found('retailer %s does not exist' % rid)
    return rec


@bp.post('/retailers')
def create_retailer():
    uid, role = authenticate()
    body = parse_body()
    store_name = req_str(body, 'store_name')
    jurisdiction = req_enum(body, 'jurisdiction_code', JURISDICTIONS)
    terms = req_enum(body, 'credit_terms', CREDIT_TERMS)
    limit = req_int(body, 'credit_limit_cents')
    day = req_enum(body, 'delivery_day', DELIVERY_DAYS)
    tobacco = opt_str(body, 'tobacco_license_id')
    require_role(role, ('WholesaleAdmin',))

    rec = new_record()
    rec.update({
        'store_name': store_name,
        'jurisdiction_code': jurisdiction,
        'credit_terms': terms,
        'credit_limit_cents': limit,
        'credit_status': 'GOOD_STANDING',
        'tobacco_license_id': tobacco,
        'ar_balance_cents': 0,
        'exposure_forward_cents': 0,
        'delivery_day': day,
        '_manual_hold': False,
    })
    STORE['retailers'][rec['id']] = rec
    return ok_object(public(rec), 201)


@bp.get('/retailers/<rid>')
def get_retailer(rid):
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'CreditManager', 'SalesRep', 'StoreManager'))
    rec = get_retailer_or_404(rid)
    check_store_ownership(uid, role, rec['id'])
    return ok_object(public(rec))


@bp.get('/retailers/<rid>/credit-summary')
def get_credit_summary(rid):
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'CreditManager', 'StoreManager'))
    rec = get_retailer_or_404(rid)
    check_store_ownership(uid, role, rec['id'])
    return ok_object(credit_summary(rec))


@bp.patch('/retailers/<rid>')
def update_retailer(rid):
    uid, role = authenticate()
    body = parse_body()
    terms = opt_enum(body, 'credit_terms', CREDIT_TERMS)
    limit = opt_int(body, 'credit_limit_cents')
    tobacco = None
    tobacco_present = 'tobacco_license_id' in body
    if tobacco_present:
        tobacco = opt_str(body, 'tobacco_license_id')
    require_role(role, ('CreditManager',))
    rec = get_retailer_or_404(rid)

    if terms is not None:
        rec['credit_terms'] = terms
    if limit is not None:
        rec['credit_limit_cents'] = limit
    if tobacco_present:
        rec['tobacco_license_id'] = tobacco
    refresh_retailer(rec)
    return ok_object(public(rec))


@bp.post('/retailers/<rid>/credit-hold')
def credit_hold(rid):
    uid, role = authenticate()
    body = parse_body()
    hold = req_bool(body, 'hold')
    require_role(role, ('CreditManager',))
    rec = get_retailer_or_404(rid)
    rec['_manual_hold'] = hold
    refresh_retailer(rec)
    return ok_object(public(rec))


@bp.get('/retailers/<rid>/order-guides')
def list_retailer_order_guides(rid):
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'SalesRep', 'StoreManager'))
    limit, offset = parse_pagination()
    rec = get_retailer_or_404(rid)
    check_store_ownership(uid, role, rec['id'])
    guides = [g for g in STORE['order_guides'].values() if g['retailer_id'] == rid]
    page, total = list_page(guides, public, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get('/retailers/<rid>/retail-prices')
def list_retailer_prices(rid):
    uid, role = authenticate()
    require_role(role, ('WholesaleAdmin', 'SalesRep', 'StoreManager'))
    limit, offset = parse_pagination()
    rec = get_retailer_or_404(rid)
    check_store_ownership(uid, role, rec['id'])
    records = [r for r in STORE['retail_price_records'].values() if r['retailer_id'] == rid]
    product_id = request.args.get('product_id')
    status = request.args.get('status')
    if product_id is not None:
        records = [r for r in records if r['product_id'] == product_id]
    if status is not None:
        records = [r for r in records if r['status'] == status]
    page, total = list_page(records, public, limit, offset)
    return ok_list(page, limit, offset, total)
