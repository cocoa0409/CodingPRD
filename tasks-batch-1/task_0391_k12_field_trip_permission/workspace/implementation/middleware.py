"""Auth header extraction and RBAC checks (PRD §2.1, §2.11)."""
from functools import wraps

from flask import request

from errors import err

KNOWN_ROLES = {"Teacher", "Principal", "DistrictAdmin", "Guardian"}


def get_user_context():
    """Validate the X-User-ID / X-User-Role headers (priority 1, 401)."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in KNOWN_ROLES:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT",
            "X-User-ID and X-User-Role headers must be present and the role known.",
        )
    return user_id, user_role


def require_roles(*allowed_roles):
    """Decorator: header validity (401) then role permission (403).

    The decorated view receives user_id and user_role as keyword arguments.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, user_role = get_user_context()
            if user_role not in allowed_roles:
                raise err(
                    "ERR_FORBIDDEN_ROLE",
                    "The acting role is not permitted to invoke this operation.",
                )
            kwargs["user_id"] = user_id
            kwargs["user_role"] = user_role
            return fn(*args, **kwargs)
        return wrapper
    return decorator
