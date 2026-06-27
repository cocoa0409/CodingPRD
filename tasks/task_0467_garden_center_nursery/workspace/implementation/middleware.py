"""Auth header extraction + RBAC (PRD §2.1, §2.10 priorities 1-2)."""
from functools import wraps

from flask import request

import errors
from errors import err

VALID_ROLES = {"PlatformAdmin", "InventoryManager", "SalesClerk"}


def get_user_context():
    """Validate X-User-ID / X-User-Role; raise on missing/invalid (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "Missing or invalid X-User-ID / X-User-Role")
    return user_id, role


def require_roles(*allowed):
    """Decorator: validate auth (priority 1) then RBAC (priority 2)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _, role = get_user_context()
            if role not in allowed:
                err(errors.ERR_INSUFFICIENT_PERMISSIONS,
                    "Role not permitted for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def parse_pagination():
    """limit default 10 (1..100), offset default 0 (>=0). Bad shape -> 422."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            err(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit_v < 1 or limit_v > 100:
            err(errors.ERR_INVALID_REQUEST, "limit out of range 1..100")
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            err(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset_v < 0:
            err(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit_v, offset_v


def paginate(items, limit, offset):
    """items already sorted; returns the page slice."""
    return items[offset:offset + limit]
