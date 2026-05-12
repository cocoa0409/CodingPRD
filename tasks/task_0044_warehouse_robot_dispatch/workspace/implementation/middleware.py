"""Auth middleware: extracts X-User-ID / X-User-Role from each request."""
from __future__ import annotations

from flask import request, g

from errors import raise_error

VALID_ROLES = {"Operator", "FleetAdmin", "WMS"}


def authenticate():
    """Validate the auth header pair. Raises ERR_UNAUTHENTICATED on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise_error("ERR_UNAUTHENTICATED", "Missing or invalid auth headers")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(allowed: list[str]):
    """Check the caller's role is in the allowed set, else ERR_FORBIDDEN."""
    role = getattr(g, "user_role", None)
    if role not in allowed:
        raise_error("ERR_FORBIDDEN", "Role not permitted for this endpoint")
