"""Member routes."""
from flask import Blueprint

from common import stamp_new, get_json_body
from db import db
from errors import api_error
from middleware import require_roles, get_auth
from response import success

bp = Blueprint("members", __name__)


@bp.route("/members", methods=["POST"])
def create_member():
    user_id, role = require_roles(["PlatformAdmin", "TenantAdmin"])
    body = get_json_body()

    tenant_id = body.get("tenant_id")
    email = body.get("email")
    full_name = body.get("full_name")
    role_in_tenant = body.get("role_in_tenant", "STAFF")

    if not tenant_id:
        raise api_error("ERR_REFERENCED_ENTITY_MISSING", "tenant_id required")
    tenant = db.tenants.get(tenant_id)
    if not tenant:
        raise api_error("ERR_REFERENCED_ENTITY_MISSING", "tenant not found")

    if not email or not isinstance(email, str):
        raise api_error("ERR_INVALID_TIME_WINDOW", "email required")
    if not full_name:
        raise api_error("ERR_INVALID_TIME_WINDOW", "full_name required")
    if role_in_tenant not in ("ADMIN", "STAFF"):
        raise api_error("ERR_INVALID_TIME_WINDOW", "invalid role_in_tenant")

    if tenant["status"] not in ("ACTIVE", "TERMINATING"):
        raise api_error("ERR_INVALID_TIME_WINDOW", "tenant not accepting new members")

    # Email unique
    for m in db.members.values():
        if m["email"] == email:
            raise api_error("ERR_INVALID_TIME_WINDOW", "email already exists")

    # TenantAdmin can only add members to own tenant
    if role == "TenantAdmin":
        caller = db.members.get(user_id)
        if not caller or caller["tenant_id"] != tenant_id:
            raise api_error("ERR_FORBIDDEN", "TenantAdmin may only add members to own tenant")

    member = {
        "tenant_id": tenant_id,
        "email": email,
        "full_name": full_name,
        "role_in_tenant": role_in_tenant,
        "status": "ACTIVE",
    }
    stamp_new(member)
    db.members[member["id"]] = member
    return success(member, status=201)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    require_roles(["PlatformAdmin", "TenantAdmin", "TenantMember"])
    member = db.members.get(member_id)
    if not member:
        raise api_error("ERR_NOT_FOUND", "member not found")
    return success(member)
