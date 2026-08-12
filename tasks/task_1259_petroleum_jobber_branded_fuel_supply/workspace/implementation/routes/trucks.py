from flask import Blueprint

import db
import serializers
from errors import err, ERR_VALIDATION_FAILED
from middleware import ALL_ROLES, auth_context, require_role
from response import ok_object
from validate import (get_body, list_response, sorted_default, validate_body)

bp = Blueprint('trucks', __name__)


@bp.route('/api/trucks', methods=['POST'])
def create_truck():
    uid, role = auth_context()
    require_role(role, {'JobberAdmin'})
    body = validate_body(get_body(), {
        'truck_code': {'type': 'str', 'required': True},
        'capacity_gallons': {'type': 'int', 'required': True, 'gt': 0},
    })
    if any(t['truck_code'] == body['truck_code']
           for t in db.STORE['trucks'].values()):
        raise err(ERR_VALIDATION_FAILED, 'Duplicate truck_code')
    rec = {
        'id': db.new_id(),
        'truck_code': body['truck_code'],
        'capacity_gallons': body['capacity_gallons'],
    }
    db.stamp_new(rec)
    db.STORE['trucks'][rec['id']] = rec
    return ok_object(serializers.truck(rec), 201)


@bp.route('/api/trucks', methods=['GET'])
def list_trucks():
    uid, role = auth_context()
    require_role(role, set(ALL_ROLES))
    items = sorted_default(db.STORE['trucks'].values())
    return list_response(items, serializers.truck)
