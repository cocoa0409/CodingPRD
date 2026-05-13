"""Authentication, RBAC, and pagination helpers."""
from functools import wraps
from flask import request, g

from errors import err


VALID_ROLES = {"Reader", "Librarian", "FineOfficer", "ILLCoordinator", "Admin"}


def get_user():
    """Read X-User-ID and X-User-Role. Raises ERR_AUTH_REQUIRED if either is missing
    or if the role value is not recognized.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_AUTH_REQUIRED", "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err("ERR_AUTH_REQUIRED", f"Unrecognized role: {role}")
    return user_id, role


def require_auth(roles=None):
    """Decorator: enforce auth header presence and (optionally) role membership."""
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
    """Read limit + offset query params with defaults & bounds per PRD §2.3."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err("ERR_INVALID_INPUT", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_INVALID_INPUT", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_INPUT", "limit must be between 1 and 100")
    if offset < 0:
        raise err("ERR_INVALID_INPUT", "offset must be a non-negative integer")
    return limit, offset
