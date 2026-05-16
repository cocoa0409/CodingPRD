"""Auth middleware + RBAC helpers."""

from functools import wraps

from flask import g, request

from config import ROLES
from errors import APIError


def require_auth(allowed_roles):
    """Decorator that enforces presence of X-User-ID/X-User-Role and role
    membership. Stashes them on flask.g for downstream use.

    Validation priority:
      1. headers present + role recognized -> else ERR_AUTH_REQUIRED
      2. role in allowed_roles -> else ERR_FORBIDDEN
    """

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if not user_id or not user_role or user_role not in ROLES:
                raise APIError("ERR_AUTH_REQUIRED")
            if user_role not in allowed_roles:
                raise APIError("ERR_FORBIDDEN")
            g.user_id = user_id
            g.user_role = user_role
            return view(*args, **kwargs)
        return wrapped
    return decorator
