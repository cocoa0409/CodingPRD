"""Auth + RBAC + pagination middleware per PRD §2.1, §2.3."""
from functools import wraps

from flask import g, request

from errors import err


VALID_ROLES = {
    "TopologyEngineer",
    "TopologyApprover",
    "ControlOperator",
    "MaintenanceSupervisor",
    "Technician",
    "Auditor",
}


def get_user():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED on missing/empty header."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_UNAUTHENTICATED", "Missing or empty X-User-ID header")
    if not role or not isinstance(role, str) or not role.strip():
        raise err("ERR_UNAUTHENTICATED", "Missing or empty X-User-Role header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", f"Unrecognized role: {role}")
    return user_id, role


def require_auth(roles=None):
    """Decorator: enforce auth and optional role allow-list."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_user()
            g.user_id = user_id
            g.user_role = role
            if roles is not None and role not in roles:
                raise err("ERR_FORBIDDEN", f"Role {role} not permitted for this endpoint")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err("ERR_BAD_REQUEST", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_BAD_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_BAD_REQUEST", "limit must be in [1, 100]")
    if offset < 0:
        raise err("ERR_BAD_REQUEST", "offset must be non-negative")
    return limit, offset


def get_json_body() -> dict:
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False)
    except Exception:
        raise err("ERR_BAD_REQUEST", "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_BAD_REQUEST", "Request body must be a JSON object")
    return body
