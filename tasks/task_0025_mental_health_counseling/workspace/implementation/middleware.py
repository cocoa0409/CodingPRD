"""Auth + RBAC middleware and pagination helpers."""
from functools import wraps
from flask import request, g

from errors import err

VALID_ROLES = {
    "Public",
    "Client",
    "Counselor",
    "Supervisor",
    "CrisisResponder",
    "PlatformAdmin",
}


def get_user(allow_public: bool = False):
    """Return (user_id, role). Raises ERR_AUTH_MISSING if missing/unrecognized.

    When allow_public is True, missing headers are interpreted as Public/anonymous.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        if allow_public:
            return None, "Public"
        raise err("ERR_AUTH_MISSING", "Missing or malformed X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or not isinstance(role, str):
        raise err("ERR_AUTH_MISSING", "Headers must be strings")
    if role not in VALID_ROLES:
        raise err("ERR_AUTH_MISSING", f"Unrecognized role: {role}")
    return user_id, role


def require_auth(roles=None, allow_public: bool = False):
    """Decorator: enforce auth + role membership."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_user(allow_public=allow_public)
            g.user_id = user_id
            g.user_role = role
            if roles is not None and role not in roles:
                raise err("ERR_FORBIDDEN", f"Role {role} not authorized for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_pagination():
    """Parse limit + offset query params per scaffold defaults
    (default 10, min 1, max 100, offset >= 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err("ERR_PAGINATION_INVALID", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_PAGINATION_INVALID", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_PAGINATION_INVALID", "limit must be in [1, 100]")
    if offset < 0:
        raise err("ERR_PAGINATION_INVALID", "offset must be >= 0")
    return limit, offset
