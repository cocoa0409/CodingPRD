"""Auth + RBAC + pagination middleware per PRD §2.1, §2.3."""
from functools import wraps
from flask import request, g

from errors import err


VALID_ROLES = {
    "ExamAdmin",
    "Proctor",
    "Candidate",
    "Marker",
    "AppealOfficer",
    "TestHarness",
}


def get_user():
    """Return (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER on issue."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "Missing X-User-ID or X-User-Role header",
        )
    if not isinstance(user_id, str) or not user_id.strip():
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID must be a non-empty string",
        )
    if not isinstance(role, str) or not role.strip():
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-Role must be a non-empty string",
        )
    if role not in VALID_ROLES:
        raise err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            f"Unrecognized role: {role}",
        )
    return user_id, role


def require_auth(roles=None):
    """Decorator: require auth headers; if `roles` is set, restrict to those roles."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_user()
            g.user_id = user_id
            g.user_role = role
            if roles is not None and role not in roles:
                raise err(
                    "ERR_INSUFFICIENT_PERMISSIONS",
                    f"Role {role} not authorized for this operation",
                )
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_pagination():
    """Read limit + offset query params per PRD §2.3."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err("ERR_INVALID_PAGINATION_PARAMETERS", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_INVALID_PAGINATION_PARAMETERS", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_PAGINATION_PARAMETERS", "limit out of range [1,100]")
    if offset < 0:
        raise err("ERR_INVALID_PAGINATION_PARAMETERS", "offset must be non-negative")
    return limit, offset


def get_json_body() -> dict:
    """Return the JSON body or {} (and raise on malformed JSON)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False)
    except Exception:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", "Request body must be a JSON object")
    return body
