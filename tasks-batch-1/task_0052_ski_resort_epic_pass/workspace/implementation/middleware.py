"""Auth header extraction and RBAC (PRD §2.1)."""
from flask import request

import errors

KNOWN_ROLES = {"NetworkAdmin", "ResortOps", "RefundAdmin"}


def authenticate():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.auth_missing()
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise errors.forbidden()
