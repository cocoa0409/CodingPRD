"""Auth + RBAC middleware."""
from functools import wraps
from flask import request, g

from errors import err

VALID_ROLES = {
    "PropertyManager",
    "LeasingAgent",
    "FinanceOfficer",
    "Tenant",
}


def get_user():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if missing/unrecognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", f"Unrecognized role: {role}")
    return user_id, role


def require_auth(roles=None):
    """Decorator: require X-User-ID + X-User-Role; if `roles` set, require role membership."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_user()
            g.user_id = user_id
            g.user_role = role
            if roles is not None and role not in roles:
                raise err("ERR_FORBIDDEN", f"Role {role} not authorized for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_pagination():
    """Read limit + offset query params, with defaults and bounds."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset
