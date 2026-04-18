from flask import Blueprint, request, g

from errors import raise_error, ERR_NOT_FOUND, ERR_REFERENCED_ENTITY_MISSING, ERR_FORBIDDEN
from response import success
from middleware import require_roles
from util import add_common_fields
from db import db

bp = Blueprint("members", __name__)


def member_view(m: dict) -> dict:
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "tenant_id": m["tenant_id"],
        "email": m["email"],
        "full_name": m["full_name"],
        "role_in_tenant": m["role_in_tenant"],
        "status": m["status"],
    }


@bp.route("/members", methods=["POST"])
def create_member():
    require_roles("PlatformAdmin", "TenantAdmin")
    body = request.get_json(silent=True) or {}
    tenant_id = body.get("tenant_id")
    email = body.get("email")
    full_name = body.get("full_name")
    role_in_tenant = body.get("role_in_tenant", "STAFF")

    if not tenant_id:
        raise_error(("ERR_INVALID_INPUT", 422), "tenant_id is required")
    if not isinstance(email, str) or "@" not in email:
        raise_error(("ERR_INVALID_INPUT", 422), "email is required")
    if not isinstance(full_name, str) or len(full_name) < 1:
        raise_error(("ERR_INVALID_INPUT", 422), "full_name is required")
    if role_in_tenant not in ("ADMIN", "STAFF"):
        raise_error(("ERR_INVALID_INPUT", 422), "role_in_tenant must be ADMIN or STAFF")

    tenant = db.tenants.get(tenant_id)
    if not tenant:
        raise_error(ERR_REFERENCED_ENTITY_MISSING, "Tenant not found")
    if tenant["status"] == "CLOSED":
        raise_error(("ERR_INVALID_INPUT", 422), "Tenant is closed")

    # Only PlatformAdmin or TenantAdmin of the same tenant
    if g.user_role == "TenantAdmin":
        m = g.acting_member
        if not m or m["tenant_id"] != tenant_id:
            raise_error(ERR_FORBIDDEN, "Cannot add member to another tenant")

    # Email uniqueness
    if db.member_by_email(email):
        raise_error(("ERR_INVALID_INPUT", 422), "Email already exists")

    member = {
        "tenant_id": tenant_id,
        "email": email,
        "full_name": full_name,
        "role_in_tenant": role_in_tenant,
        "status": "ACTIVE",
    }
    add_common_fields(member, db.now(), db.new_id())
    db.members[member["id"]] = member
    return success(member_view(member), 201)


@bp.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    require_roles("PlatformAdmin", "TenantAdmin", "TenantMember")
    m = db.members.get(member_id)
    if not m:
        raise_error(ERR_NOT_FOUND, "Member not found")
    # TenantAdmin/TenantMember must be in same tenant
    if g.user_role in ("TenantAdmin", "TenantMember"):
        actor = g.acting_member
        if not actor or actor["tenant_id"] != m["tenant_id"]:
            raise_error(ERR_FORBIDDEN, "Member not accessible")
    return success(member_view(m))
