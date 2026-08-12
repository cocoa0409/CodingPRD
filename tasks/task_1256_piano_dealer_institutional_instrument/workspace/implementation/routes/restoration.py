from flask import Blueprint, request

import db
from errors import ApiError, invalid
from middleware import auth
from response import ok, ok_list
from util import body, require, as_str, as_int, find, serialize

bp = Blueprint('restoration', __name__)


def _not_actionable(message='referral is not in the required state'):
    return ApiError('ERR_REFERRAL_NOT_ACTIONABLE', 409, message)


@bp.post('/piano-dealer/restoration-referrals')
def create_referral():
    auth('StoreManager')
    d = body()
    instrument_id = as_str(require(d, 'instrument_id'), 'instrument_id')
    shop_name = as_str(require(d, 'shop_name'), 'shop_name')
    find(db.stores['instruments'], instrument_id, 'instrument')
    rec = db.base_fields()
    rec.update({
        'instrument_id': instrument_id,
        'shop_name': shop_name,
        'condition_score': None,
        'estimate_low_cents': None,
        'estimate_high_cents': None,
        'final_quote_cents': None,
        'status': 'REFERRED',
    })
    db.stores['referrals'][rec['id']] = rec
    return ok(serialize(rec), 201)


@bp.get('/piano-dealer/restoration-referrals/<rid>')
def get_referral(rid):
    auth('StoreManager')
    return ok(serialize(find(db.stores['referrals'], rid, 'referral')))


@bp.get('/piano-dealer/restoration-referrals')
def list_referrals():
    auth('StoreManager')
    items = list(db.stores['referrals'].values())
    instrument_id = request.args.get('instrument_id')
    if instrument_id:
        items = [r for r in items if r['instrument_id'] == instrument_id]
    return ok_list(items, serialize)


@bp.post('/piano-dealer/restoration-referrals/<rid>/assess')
def assess_referral(rid):
    auth('StoreManager')
    ref = find(db.stores['referrals'], rid, 'referral')
    d = body()
    score = as_int(require(d, 'condition_score'), 'condition_score')
    low = as_int(require(d, 'estimate_low_cents'), 'estimate_low_cents')
    high = as_int(require(d, 'estimate_high_cents'), 'estimate_high_cents')
    if not (1 <= score <= 100):
        raise invalid('condition_score must be between 1 and 100')
    if ref['status'] != 'REFERRED':
        raise _not_actionable('only REFERRED referrals can be assessed')
    ref['condition_score'] = score
    ref['estimate_low_cents'] = low
    ref['estimate_high_cents'] = high
    ref['status'] = 'ASSESSED'
    db.touch(ref)
    return ok(serialize(ref))


@bp.post('/piano-dealer/restoration-referrals/<rid>/quote')
def quote_referral(rid):
    auth('StoreManager')
    ref = find(db.stores['referrals'], rid, 'referral')
    d = body()
    quote = as_int(require(d, 'final_quote_cents'), 'final_quote_cents')
    if ref['status'] != 'ASSESSED':
        raise _not_actionable('only ASSESSED referrals can be quoted')
    ref['final_quote_cents'] = quote
    ref['status'] = 'QUOTED'
    db.touch(ref)
    return ok(serialize(ref))


@bp.post('/piano-dealer/restoration-referrals/<rid>/record-decision')
def record_decision(rid):
    auth('StoreManager')
    ref = find(db.stores['referrals'], rid, 'referral')
    d = body()
    decision = require(d, 'decision')
    if decision not in ('COMMISSIONED', 'DECLINED'):
        raise invalid('decision must be COMMISSIONED or DECLINED')
    if ref['status'] != 'QUOTED':
        raise _not_actionable('only QUOTED referrals can record a decision')
    if decision == 'COMMISSIONED':
        inst = find(db.stores['instruments'], ref['instrument_id'], 'instrument')
        if inst['status'] != 'AVAILABLE':
            raise ApiError('ERR_INSTRUMENT_NOT_AVAILABLE', 409,
                           'instrument must be AVAILABLE to commission restoration')
        inst['status'] = 'RESTORATION_HOLD'
        db.touch(inst)
    ref['status'] = decision
    db.touch(ref)
    return ok(serialize(ref))
