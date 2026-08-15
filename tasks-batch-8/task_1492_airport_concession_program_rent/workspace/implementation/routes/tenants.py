"""Tenant endpoints (PRD section 3.1)."""
from flask import Blueprint, g

from db import db, base_fields
from errors import ApiError, ERR_NOT_FOUND, ERR_FORBIDDEN
from middleware import require_roles, body_json, req_str
from response import ok, ok_list
from services.core import pub
from services.validation import paginate

bp = Blueprint('tenants', __name__)


@bp.route('/concessions/tenants', methods=['POST'])
def create_tenant():
    require_roles('AirportAdmin')
    body = body_json()
    legal_name = req_str(body, 'legal_name')
    contact_email = req_str(body, 'contact_email')
    acdbe_certified = body.get('acdbe_certified', False)
    if not isinstance(acdbe_certified, bool):
        from errors import ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST, 400, 'Field malformed: acdbe_certified')
    rec = base_fields()
    rec.update({
        'legal_name': legal_name,
        'contact_email': contact_email,
        'acdbe_certified': acdbe_certified,
    })
    db.tenants[rec['id']] = rec
    return ok(pub(rec), status=201)


@bp.route('/concessions/tenants', methods=['GET'])
def list_tenants():
    require_roles('AirportAdmin', 'ConcessionAnalyst')
    items = sorted(db.tenants.values(), key=lambda t: t['_seq'])
    page, meta = paginate(items)
    return ok_list([pub(t) for t in page], meta)


@bp.route('/concessions/tenants/<tid>', methods=['GET'])
def get_tenant(tid):
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    t = db.tenants.get(tid)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Tenant not found')
    # A Tenant may read its own tenant record only.
    if g.role == 'Tenant' and g.user_id != tid:
        raise ApiError(ERR_FORBIDDEN, 403, 'Tenant may read only its own tenant record')
    return ok(pub(t))
