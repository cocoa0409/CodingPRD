from datetime import timedelta

from flask import Blueprint, request

import calc
import db
from errors import ApiError, forbidden
from middleware import auth
from response import ok, ok_list
from util import body, require, as_str, as_int, as_num, as_enum, find, serialize

bp = Blueprint('appraisals', __name__)

CATEGORIES = ('GRAND', 'UPRIGHT', 'DIGITAL', 'HYBRID')
CONDITIONS = ('EXCELLENT', 'GOOD', 'FAIR', 'POOR')
DT_FIELDS = ('offered_at',)


def ser(appraisal):
    return serialize(appraisal, DT_FIELDS)


def _not_offered():
    return ApiError('ERR_APPRAISAL_NOT_OFFERED', 409, 'appraisal is not in the required state')


def _check_owner(appraisal, uid):
    if appraisal['customer_id'] != uid:
        raise forbidden('customer may only act on their own appraisal')


def _check_offer_window(appraisal):
    """Lazy expiry: accept/counter after offered_at + 14 days flips to EXPIRED and fails."""
    if appraisal['offered_at'] is not None and db.now() > appraisal['offered_at'] + timedelta(days=calc.OFFER_TTL_DAYS):
        appraisal['status'] = 'EXPIRED'
        db.touch(appraisal)
        raise ApiError('ERR_APPRAISAL_EXPIRED', 409, 'the offer window has expired')


@bp.post('/piano-dealer/trade-in-appraisals')
def create_appraisal():
    auth('SalesAssociate')
    d = body()
    customer_id = as_str(require(d, 'customer_id'), 'customer_id')
    category = as_enum(require(d, 'category'), 'category', CATEGORIES)
    manufacturer = as_str(require(d, 'manufacturer'), 'manufacturer')
    model = as_str(require(d, 'model'), 'model')
    year_built = as_int(require(d, 'year_built'), 'year_built')
    condition_grade = as_enum(require(d, 'condition_grade'), 'condition_grade', CONDITIONS)
    find(db.stores['customers'], customer_id, 'customer')
    rec = db.base_fields()
    rec.update({
        'customer_id': customer_id,
        'category': category,
        'manufacturer': manufacturer,
        'model': model,
        'year_built': year_built,
        'condition_grade': condition_grade,
        'provisional_value_cents': calc.trade_in_provisional(category, year_built, condition_grade),
        'reconditioning_cost_cents': None,
        'market_adjustment_pct': None,
        'final_value_cents': None,
        'counter_value_cents': None,
        'offered_at': None,
        'status': 'SUBMITTED',
    })
    db.stores['appraisals'][rec['id']] = rec
    return ok(ser(rec), 201)


@bp.get('/piano-dealer/trade-in-appraisals/<rid>')
def get_appraisal(rid):
    uid, role = auth('SalesAssociate', 'Customer')
    appraisal = find(db.stores['appraisals'], rid, 'appraisal')
    if role == 'Customer':
        _check_owner(appraisal, uid)
    return ok(ser(appraisal))


@bp.get('/piano-dealer/trade-in-appraisals')
def list_appraisals():
    auth('SalesAssociate')
    items = list(db.stores['appraisals'].values())
    customer_id = request.args.get('customer_id')
    if customer_id:
        items = [a for a in items if a['customer_id'] == customer_id]
    return ok_list(items, ser)


@bp.post('/piano-dealer/trade-in-appraisals/<rid>/evaluate')
def evaluate_appraisal(rid):
    auth('StoreManager')
    appraisal = find(db.stores['appraisals'], rid, 'appraisal')
    d = body()
    recon = as_int(require(d, 'reconditioning_cost_cents'), 'reconditioning_cost_cents')
    adj_raw = as_num(require(d, 'market_adjustment_pct'), 'market_adjustment_pct')
    if appraisal['status'] not in ('SUBMITTED', 'COUNTERED'):
        raise _not_offered()
    adj = calc.clamp_market_adj(adj_raw)
    appraisal['reconditioning_cost_cents'] = recon
    appraisal['market_adjustment_pct'] = float(adj)
    appraisal['final_value_cents'] = calc.trade_in_final(
        appraisal['provisional_value_cents'], recon, adj)
    appraisal['offered_at'] = db.now()
    appraisal['status'] = 'OFFERED'
    db.touch(appraisal)
    return ok(ser(appraisal))


@bp.post('/piano-dealer/trade-in-appraisals/<rid>/counter')
def counter_appraisal(rid):
    uid, role = auth('Customer')
    appraisal = find(db.stores['appraisals'], rid, 'appraisal')
    _check_owner(appraisal, uid)
    d = body()
    counter_value = as_int(require(d, 'counter_value_cents'), 'counter_value_cents')
    if appraisal['status'] != 'OFFERED':
        raise _not_offered()
    _check_offer_window(appraisal)
    appraisal['counter_value_cents'] = counter_value
    appraisal['status'] = 'COUNTERED'
    db.touch(appraisal)
    return ok(ser(appraisal))


@bp.post('/piano-dealer/trade-in-appraisals/<rid>/accept')
def accept_appraisal(rid):
    uid, role = auth('Customer')
    appraisal = find(db.stores['appraisals'], rid, 'appraisal')
    _check_owner(appraisal, uid)
    if appraisal['status'] != 'OFFERED':
        raise _not_offered()
    _check_offer_window(appraisal)
    appraisal['status'] = 'ACCEPTED'
    db.touch(appraisal)
    return ok(ser(appraisal))


@bp.post('/piano-dealer/trade-in-appraisals/<rid>/decline')
def decline_appraisal(rid):
    uid, role = auth('Customer')
    appraisal = find(db.stores['appraisals'], rid, 'appraisal')
    _check_owner(appraisal, uid)
    if appraisal['status'] != 'OFFERED':
        raise _not_offered()
    appraisal['status'] = 'DECLINED'
    db.touch(appraisal)
    return ok(ser(appraisal))
