"""Auth: X-User-ID / X-User-Role header extraction and role gating (PRD §2.1)."""
from flask import g, request

from errors import ApiError

ROLES = [
    "RegionalManager",
    "PropertyManager",
    "TurnCoordinator",
    "Vendor",
    "Inspector",
    "PlatformAdmin",
]


def authenticate():
    """Validation chain step 1: both headers present and role is declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers are required and the "
                       "role must be one of the declared roles")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_roles(allowed):
    """Validation chain step 2: the declared role is permitted on the endpoint."""
    role = getattr(g, "user_role", None)
    if role is None:
        authenticate()
        role = g.user_role
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Role %s is not permitted on this endpoint" % role)
