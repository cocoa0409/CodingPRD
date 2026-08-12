from flask import Blueprint, request

import db
import serializers
from errors import err, ERR_VALIDATION_FAILED
from middleware import ALL_ROLES, auth_context, require_role
from response import ok_object
from validate import (apply_filters, get_body, list_response, sorted_default,
                      validate_body)

bp = Blueprint('products', __name__)


@bp.route('/api/products', methods=['POST'])
def create_product():
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    body = validate_body(get_body(), {
        'product_code': {'type': 'str', 'required': True},
        'display_name': {'type': 'str', 'required': True},
        'category': {'type': 'enum', 'required': True,
                     'enum': ['GASOLINE', 'DIESEL']},
        'federal_excise_tc_per_gal': {'type': 'int', 'required': True},
        'temp_coeff': {'type': 'number', 'required': True, 'gt': 0},
    })
    # Duplicate product_code is reported at the shape-and-integrity level.
    if any(p['product_code'] == body['product_code']
           for p in db.STORE['products'].values()):
        raise err(ERR_VALIDATION_FAILED, 'Duplicate product_code')
    rec = {
        'id': db.new_id(),
        'product_code': body['product_code'],
        'display_name': body['display_name'],
        'category': body['category'],
        'federal_excise_tc_per_gal': body['federal_excise_tc_per_gal'],
        'temp_coeff': body['temp_coeff'],
    }
    db.stamp_new(rec)
    db.STORE['products'][rec['id']] = rec
    return ok_object(serializers.product(rec), 201)


@bp.route('/api/products', methods=['GET'])
def list_products():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted_default(db.STORE['products'].values())
    items = apply_filters(items, {'category': request.args.get('category')})
    return list_response(items, serializers.product)
