"""Business owner registration and detail (PRD §3.4)."""

from flask import Blueprint

from db import new_id, stamp_new, store
from middleware import (ALL_ROLES, auth_context, get_body, get_or_404,
                        req_str, require_roles)
from response import success_object
from serializers import business_owner_to_api
from services.audit import append_audit

bp = Blueprint("business_owners", __name__)


@bp.post("/compliance/business-owners")
def create_business_owner():
    user_id, role = auth_context()
    require_roles(role, ("ComplianceOfficer",))
    body = get_body()
    name = req_str(body, "name")
    department = req_str(body, "department")
    email = req_str(body, "email")

    owner = stamp_new({
        "id": new_id(),
        "name": name,
        "department": department,
        "email": email,
    })
    store.business_owners[owner["id"]] = owner
    append_audit(user_id, role, "POST /compliance/business-owners",
                 "BusinessOwner", owner["id"])
    return success_object(business_owner_to_api(owner), status=201)


@bp.get("/compliance/business-owners/<owner_id>")
def get_business_owner(owner_id):
    auth_context()  # all roles may read
    owner = get_or_404(store.business_owners, owner_id, "business owner")
    return success_object(business_owner_to_api(owner))
