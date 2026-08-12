from flask import Blueprint, request

import db
import serializers
from errors import (err, ERR_DEALER_STATION_NOT_FOUND,
                    ERR_PRODUCT_NOT_FOUND, ERR_STORAGE_TANK_NOT_FOUND)
from middleware import (ALL_ROLES, auth_context, dealer_scope_check,
                        require_role, scoped)
from response import ok_object
from services import cascade
from validate import (apply_filters, get_body, list_response, sorted_default,
                      validate_body)

bp = Blueprint('tanks', __name__)


@bp.route('/api/storage-tanks', methods=['POST'])
def create_tank():
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    body = validate_body(get_body(), {
        'station_id': {'type': 'str', 'required': True},
        'product_id': {'type': 'str', 'required': True},
        'capacity_gallons': {'type': 'int', 'required': True, 'gt': 0},
        'opening_physical_gallons': {'type': 'int', 'required': True,
                                     'ge': 0},
        'safe_fill_pct': {'type': 'number', 'required': False, 'gt': 0,
                          'le': 1},
    })
    db.get_or_404('stations', body['station_id'],
                  ERR_DEALER_STATION_NOT_FOUND)
    db.get_or_404('products', body['product_id'], ERR_PRODUCT_NOT_FOUND)
    rec = {
        'id': db.new_id(),
        'station_id': body['station_id'],
        'product_id': body['product_id'],
        'capacity_gallons': body['capacity_gallons'],
        'safe_fill_pct': body.get('safe_fill_pct', 0.95),
        'opening_physical_gallons': body['opening_physical_gallons'],
        'physical_gallons': body['opening_physical_gallons'],
        'physical_temp_f': None,
        'book_inventory_gallons': body['opening_physical_gallons'],
    }
    db.stamp_new(rec)
    db.STORE['tanks'][rec['id']] = rec
    return ok_object(serializers.tank(rec), 201)


@bp.route('/api/storage-tanks', methods=['GET'])
def list_tanks():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted_default(db.STORE['tanks'].values())
    items = scoped(items, uid, role, lambda t: t['station_id'])
    items = apply_filters(items, {
        'station_id': request.args.get('station_id'),
        'product_id': request.args.get('product_id'),
    })
    return list_response(items, serializers.tank)


@bp.route('/api/storage-tanks/<tid>', methods=['GET'])
def get_tank(tid):
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    rec = db.get_or_404('tanks', tid, ERR_STORAGE_TANK_NOT_FOUND)
    dealer_scope_check(uid, role, rec['station_id'])
    return ok_object(serializers.tank(rec))


@bp.route('/api/storage-tanks/<tid>/gauge', methods=['POST'])
def gauge_tank(tid):
    uid, role = auth_context()
    require_role(role, {'DealerOperator'})
    body = validate_body(get_body(), {
        'reading_gallons': {'type': 'number', 'required': True},
        'observed_temp_f': {'type': 'number', 'required': True},
    })
    rec = db.get_or_404('tanks', tid, ERR_STORAGE_TANK_NOT_FOUND)
    dealer_scope_check(uid, role, rec['station_id'])
    rec['physical_gallons'] = body['reading_gallons']
    rec['physical_temp_f'] = body['observed_temp_f']
    db.touch(rec)
    cascade.recompute_open_recon(rec['station_id'])
    return ok_object(serializers.tank(rec))
