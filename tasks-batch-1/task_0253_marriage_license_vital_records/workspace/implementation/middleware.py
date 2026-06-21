"""Auth header extraction and RBAC enforcement (PRD 2.1, 3.10; SCAFFOLD 1.4/1.7)."""
from functools import wraps

from flask import request, g

from constants import ROLES
from errors import ApiError


def authenticate():
    """Validate the two mandatory auth headers. PRD 2.1.

    Missing X-User-ID / X-User-Role, or an unknown role -> ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: authenticate, then enforce role membership.

    Order: auth (401) before authorization (403) — PRD 3.10.
    """
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                raise ApiError("ERR_FORBIDDEN", "Role not permitted for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
