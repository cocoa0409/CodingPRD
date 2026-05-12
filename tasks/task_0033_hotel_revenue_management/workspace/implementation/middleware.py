"""Auth + RBAC middleware."""
from functools import wraps
from flask import request, g

from errors import err

VALID_ROLES = {
    "PlatformAdmin",
    "RevenueAnalyst",
    "RevenueManager",
    "ReservationsAgent",
    "FrontDeskClerk",
    "HousekeepingStaff",
    "Guest",
}


def get_user():
    """Return (user_id, role). Raises ERR_AUTH_MISSING if missing."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_AUTH_MISSING", "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err("ERR_FORBIDDEN", f"Unrecognized role: {role}")
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
    """Read limit + offset query params; reject out-of-range with ERR_INVALID_PAGINATION."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err("ERR_INVALID_PAGINATION", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_INVALID_PAGINATION", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_PAGINATION", "limit must be in [1,100]")
    if offset < 0:
        raise err("ERR_INVALID_PAGINATION", "offset must be >= 0")
    return limit, offset
