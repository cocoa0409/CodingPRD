"""Tenant endpoints (PRD 3.1): registration is shared by LeasingAgent and
PropertyManager; phone defaults to the empty string; email is unique."""

from flask import Blueprint

import db
import errors
import middleware
import response
import serializers
import validators as V

bp = Blueprint("tenants", __name__)


@bp.post("/tenants")
def create_tenant():
    _uid, role = middleware.current_user()
    middleware.require_role(role, {"LeasingAgent", "PropertyManager"})
    data = V.json_body()
    V.check_unknown(data, {"full_name", "email", "phone"})
    full_name = V.req_str(data, "full_name")
    email = V.req_str(data, "email")
    phone = V.opt_str(data, "phone", "")
    for t in db.tenants.values():
        if t["email"] == email:
            errors.fail(
                errors.ERR_INVALID_REQUEST,
                "A tenant with email %s already exists." % email,
            )
    tenant = db.init_common({
        "full_name": full_name,
        "email": email,
        "phone": phone,
    })
    db.tenants[tenant["id"]] = tenant
    return response.success_object(serializers.tenant_view(tenant), 201)
