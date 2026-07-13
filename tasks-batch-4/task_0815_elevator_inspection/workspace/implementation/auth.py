"""Authentication and role-based access enforcement."""

import functools

from flask import g, request

import errors
from constants import ROLES


def load_user_context():
    """Validate the two required headers (priority 1). Populates flask.g."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.missing_or_invalid_user_context()
    g.user_id = user_id
    g.role = role
    return user_id, role


def require(*allowed_roles):
    """Decorator: enforce header presence (1) then role permission (2)."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = load_user_context()
            if role not in allowed_roles:
                raise errors.insufficient_permissions()
            return fn(*args, **kwargs)

        return wrapper

    return decorator
