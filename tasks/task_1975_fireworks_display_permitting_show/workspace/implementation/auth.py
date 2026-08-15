"""Auth: X-User-ID / X-User-Role headers, role permissioning (tiers 1-2)."""

from flask import request

from errors import err

ROLES = {"SystemAdmin", "Operator", "FireMarshal", "CrewMember"}


def authenticate():
    """Tier 1: headers present and role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", "missing or unknown X-User-ID / X-User-Role")
    return uid, role


def require_roles(*roles):
    """Tiers 1-2: authenticate, then check role permission for the endpoint."""
    uid, role = authenticate()
    if role not in roles:
        err("ERR_FORBIDDEN_ROLE", f"role {role} is not permitted on this endpoint")
    return uid, role
