from flask import Blueprint

import errors
from errors import err
from db import db
from models import make_common, serialize
from middleware import get_identity, require_role
from helpers import get_json_body, lookup
from response import success

bp = Blueprint("tenants", __name__)


@bp.post("/tenants")
def create_tenant():
    _, role = get_identity()
    require_role(role, {"FacilityManager", "Tenant"})
    body = get_json_body()

    email = body.get("email")
    full_name = body.get("full_name")
    state_code = body.get("state_code")
    phone = body.get("phone", None)

    if not isinstance(email, str) or not email:
        raise err(errors.ERR_INVALID_REQUEST, "email is required")
    if not isinstance(full_name, str) or not full_name:
        raise err(errors.ERR_INVALID_REQUEST, "full_name is required")
    if not isinstance(state_code, str) or not state_code:
        raise err(errors.ERR_INVALID_REQUEST, "state_code is required")
    if phone is not None and not isinstance(phone, str):
        raise err(errors.ERR_INVALID_REQUEST, "phone must be a string")

    for t in db.tenants.values():
        if t["email"] == email:
            raise err(errors.ERR_DUPLICATE_EMAIL, "email already registered")

    tenant = make_common()
    tenant.update({
        "email": email,
        "full_name": full_name,
        "state_code": state_code,
        "phone": phone,
    })
    db.tenants[tenant["id"]] = tenant
    return success(serialize(tenant), 201)


@bp.get("/tenants/<tenant_id>")
def get_tenant(tenant_id):
    user_id, role = get_identity()
    require_role(role, {"FacilityManager", "Tenant"})
    tenant = lookup(db.tenants, tenant_id, "tenant")
    if role == "Tenant" and user_id != tenant_id:
        raise err(errors.ERR_FORBIDDEN, "Tenant may only read their own record")
    return success(serialize(tenant), 200)
