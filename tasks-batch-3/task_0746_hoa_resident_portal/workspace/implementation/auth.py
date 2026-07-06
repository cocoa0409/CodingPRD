"""Auth header extraction and RBAC per PRD §2.1."""

from functools import wraps
from flask import request

from errors import raise_error

VALID_ROLES = {"Homeowner", "BoardMember", "ComplianceOfficer", "HOAManager"}


def get_user():
    """Return (role, user_id). Raises ERR_UNAUTHENTICATED if role missing/invalid."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in VALID_ROLES:
        raise_error("ERR_UNAUTHENTICATED", "X-User-Role missing or not recognized")
    return role, user_id


def require_role(*allowed):
    """Decorator: run auth (priority 1), then authz (priority 2)."""
    allowed_set = set(allowed)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = get_user()
            if role not in allowed_set:
                raise_error("ERR_UNAUTHORIZED", f"role {role} not permitted for this endpoint")
            return fn(*args, **kwargs)

        return wrapper

    return deco
