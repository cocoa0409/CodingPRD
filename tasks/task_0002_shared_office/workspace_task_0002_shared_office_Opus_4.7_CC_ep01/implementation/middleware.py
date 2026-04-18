from flask import request, g

from errors import raise_error, ERR_MISSING_AUTH, ERR_UNKNOWN_ROLE, ERR_FORBIDDEN
from db import db


VALID_ROLES = {
    "PlatformAdmin",
    "TenantAdmin",
    "TenantMember",
    "Receptionist",
    "BillingOfficer",
    "PaymentClerk",
}

ENTITY_BACKED_ROLES = {"TenantAdmin", "TenantMember"}


def authenticate():
    user_id = request.headers.get("X-User-ID", "").strip()
    user_role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not user_role:
        raise_error(ERR_MISSING_AUTH, "Missing X-User-ID or X-User-Role header")
    if user_role not in VALID_ROLES:
        raise_error(ERR_UNKNOWN_ROLE, f"Unknown role: {user_role}")
    g.user_id = user_id
    g.user_role = user_role
    g.acting_member = None
    if user_role in ENTITY_BACKED_ROLES:
        m = db.members.get(user_id)
        g.acting_member = m  # may be None; some checks only need role


def require_roles(*allowed_roles):
    if g.user_role not in allowed_roles:
        raise_error(ERR_FORBIDDEN, f"Role {g.user_role} not permitted")


def acting_tenant_id() -> str | None:
    """For TenantAdmin/TenantMember, returns the tenant_id derived from their member record."""
    m = g.get("acting_member")
    if m:
        return m["tenant_id"]
    return None
