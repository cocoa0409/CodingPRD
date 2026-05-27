"""Auth header extraction per PRD §2.1.

Every request must carry X-User-ID and X-User-Role. Recognised roles, spelt
exactly as below, are Guest, Restaurant, PlatformAdmin.
"""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"Guest", "Restaurant", "PlatformAdmin"}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or not user_id.strip():
        raise_err(ERR_UNAUTHENTICATED, "X-User-ID header malformed")
    if role not in VALID_ROLES:
        raise_err(ERR_UNAUTHENTICATED, f"Unknown role {role!r}")
    return user_id, role


def require_role(role: str, allowed):
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, f"Role {role!r} not permitted on this endpoint")
