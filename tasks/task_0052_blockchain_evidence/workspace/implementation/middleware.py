"""Auth + RBAC middleware (per PRD §2.1)."""
from functools import wraps

from flask import request, g

from errors import err


VALID_ROLES = {"Customer", "NotaryOfficer", "JudicialOfficer", "PlatformAdmin"}


def _read_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_AUTH_REQUIRED", "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        # An unknown role isn't authorized for any endpoint.
        raise err("ERR_PERMISSION_DENIED", f"Unrecognized role: {role}")
    return user_id, role


def require_auth(roles=None):
    """Decorator: require X-User-ID + X-User-Role; if `roles` set, require role membership.

    Auth + RBAC checks run BEFORE any path resource resolution so that
    ERR_AUTH_REQUIRED and ERR_PERMISSION_DENIED beat ERR_NOT_FOUND per §2.10.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _read_auth()
            g.user_id = user_id
            g.user_role = role
            if roles is not None and role not in roles:
                raise err("ERR_PERMISSION_DENIED", f"Role {role} not authorized for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_pagination():
    """Read limit + offset query params, with defaults and bounds per §2.3."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION_FAILED", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION_FAILED", "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset
