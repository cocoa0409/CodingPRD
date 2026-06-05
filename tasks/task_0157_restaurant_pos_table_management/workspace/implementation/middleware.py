"""Authentication + RBAC (PRD §2.1, §2.7, §4 endpoint role column)."""
from functools import wraps

from flask import request

import errors

VALID_ROLES = {"Manager", "Server", "Host", "KitchenStaff"}


def get_identity():
    """Return (user_id, role) from headers, treating blank as missing."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is not None and uid.strip() == "":
        uid = None
    if role is not None and role.strip() == "":
        role = None
    return uid, role


def require_auth(allowed_roles):
    """Decorator: priority-1 auth (401) then priority-2 role authorization (403).

    `allowed_roles` is an iterable of role names permitted for this operation.
    """
    allowed = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = get_identity()
            if not uid or not role:
                raise errors.unauthenticated()
            if role not in allowed:
                raise errors.forbidden()
            return fn(*args, **kwargs)

        return wrapper

    return decorator
