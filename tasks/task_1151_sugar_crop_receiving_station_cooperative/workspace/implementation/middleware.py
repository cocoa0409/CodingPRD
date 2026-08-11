"""Auth header extraction and role checking per PRD §2.1 and SCAFFOLD validations 1-3."""
from flask import request

from errors import raise_err

ROLES = {
    "COOP_ADMIN",
    "SCHEDULER",
    "MEMBER",
    "STATION_OPERATOR",
    "QUALITY_TECH",
    "POOL_ACCOUNTANT",
}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise_err("ERR_UNAUTHENTICATED", "X-User-Role header missing or not a declared role")
    user_id = request.headers.get("X-User-ID")
    return user_id, role


def require_roles(allowed):
    """Check that the caller's role is in `allowed`. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise_err("ERR_FORBIDDEN", "Role not allowed on this endpoint")
    return user_id, role


def check_member_ownership(user_id, role, resource_member_id):
    """MEMBER callers may only read/act on resources whose member_id == X-User-ID."""
    if role == "MEMBER" and resource_member_id != user_id:
        raise_err("ERR_FORBIDDEN", "MEMBER may only access own resources")
