from flask import Blueprint

import db
from errors import forbidden
from middleware import auth
from response import ok, ok_list
from util import body, require, as_str, as_num, as_enum, find, serialize

bp = Blueprint('consignors', __name__)


def _self_or_manager(uid, role, consignor_id):
    if role == 'Consignor' and uid != consignor_id:
        raise forbidden('a consignor may only access their own record and instruments')


@bp.post('/piano-dealer/consignors')
def create_consignor():
    auth('StoreManager')
    d = body()
    rec = db.base_fields()
    rec.update({
        'full_name': as_str(require(d, 'full_name'), 'full_name'),
        'email': as_str(require(d, 'email'), 'email'),
        'commission_pct': as_num(require(d, 'commission_pct'), 'commission_pct'),
        'split_mode': as_enum(require(d, 'split_mode'), 'split_mode', ('GROSS_SPLIT', 'NET_SPLIT')),
        'payout_method': as_enum(require(d, 'payout_method'), 'payout_method', ('CHECK', 'ACH', 'WIRE')),
        'outstanding_payout_cents': 0,
    })
    db.stores['consignors'][rec['id']] = rec
    return ok(serialize(rec), 201)


@bp.get('/piano-dealer/consignors/<rid>')
def get_consignor(rid):
    uid, role = auth('StoreManager', 'Consignor')
    _self_or_manager(uid, role, rid)
    return ok(serialize(find(db.stores['consignors'], rid, 'consignor')))


@bp.get('/piano-dealer/consignors/<rid>/instruments')
def list_consignor_instruments(rid):
    uid, role = auth('StoreManager', 'Consignor')
    _self_or_manager(uid, role, rid)
    find(db.stores['consignors'], rid, 'consignor')
    items = [i for i in db.stores['instruments'].values() if i.get('consignor_id') == rid]
    return ok_list(items, serialize)
