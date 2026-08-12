from datetime import timedelta

from flask import Blueprint, request

import calc
import db
from errors import ApiError, invalid
from middleware import auth
from response import ok, ok_list
from util import body, require, as_str, find, serialize

bp = Blueprint('warranties', __name__)

DT_FIELDS = ('registered_at', 'coverage_end')


def _maybe_expire(w):
    """Lazy EXPIRED: any read after the logical clock passes coverage_end."""
    if w['status'] == 'REGISTERED' and w.get('coverage_end') is not None \
            and db.now() > w['coverage_end']:
        w['status'] = 'EXPIRED'
        db.touch(w)


def ser(w):
    return serialize(w, DT_FIELDS)


@bp.post('/piano-dealer/warranty-registrations')
def create_warranty():
    auth('SalesAssociate')
    d = body()
    order_id = as_str(require(d, 'order_id'), 'order_id')
    instrument_id = as_str(require(d, 'instrument_id'), 'instrument_id')
    order = find(db.stores['orders'], order_id, 'order')
    find(db.stores['instruments'], instrument_id, 'instrument')
    if order['fulfillment_status'] not in ('DELIVERED', 'INSTALLED'):
        raise ApiError('ERR_DELIVERY_NOT_ACTIONABLE', 409,
                       'warranty registration requires a DELIVERED or INSTALLED order')
    if db.now() > order['delivered_at'] + timedelta(days=calc.REGISTRATION_WINDOW_DAYS):
        raise ApiError('ERR_WARRANTY_WINDOW_CLOSED', 422,
                       'registration is more than 60 days after delivery')
    if not any(item['instrument_id'] == instrument_id for item in order['items']):
        raise invalid('instrument does not appear in the order items')
    rec = db.base_fields()
    rec.update({
        'order_id': order_id,
        'instrument_id': instrument_id,
        'term_months': 24,
        'registered_at': None,
        'coverage_end': None,
        'status': 'PENDING',
    })
    db.stores['warranties'][rec['id']] = rec
    return ok(ser(rec), 201)


@bp.get('/piano-dealer/warranty-registrations/<rid>')
def get_warranty(rid):
    auth('SalesAssociate', 'StoreManager')
    w = find(db.stores['warranties'], rid, 'warranty registration')
    _maybe_expire(w)
    return ok(ser(w))


@bp.get('/piano-dealer/warranty-registrations')
def list_warranties():
    auth('SalesAssociate', 'StoreManager')
    items = list(db.stores['warranties'].values())
    order_id = request.args.get('order_id')
    instrument_id = request.args.get('instrument_id')
    if order_id:
        items = [w for w in items if w['order_id'] == order_id]
    if instrument_id:
        items = [w for w in items if w['instrument_id'] == instrument_id]
    for w in items:
        _maybe_expire(w)
    return ok_list(items, ser)


@bp.post('/piano-dealer/warranty-registrations/<rid>/confirm')
def confirm_warranty(rid):
    auth('StoreManager')
    w = find(db.stores['warranties'], rid, 'warranty registration')
    if w['status'] != 'PENDING':
        raise invalid('only PENDING registrations can be confirmed')
    order = find(db.stores['orders'], w['order_id'], 'order')
    w['registered_at'] = db.now()
    w['coverage_end'] = calc.coverage_end(order['delivered_at'], w['registered_at'])
    w['status'] = 'REGISTERED'
    db.touch(w)
    return ok(ser(w))
