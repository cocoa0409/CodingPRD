"""Auth + RBAC + pagination middleware per PRD §2.1, §2.3, §2.8."""
from functools import wraps
from flask import request, g

from errors import err


VALID_ROLES = {"Dispatcher", "Driver", "Employee", "Auditor"}


def get_user():
    """Return (user_id, role). Raises:
       - ERR_AUTH_MISSING when header missing/empty
       - ERR_INVALID_ROLE when role not in valid set
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if user_id is None or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_AUTH_MISSING", "X-User-ID header missing or empty")
    if role is None or not isinstance(role, str) or not role.strip():
        raise err("ERR_AUTH_MISSING", "X-User-Role header missing or empty")
    if role not in VALID_ROLES:
        raise err("ERR_INVALID_ROLE", f"Unrecognized role: {role}")
    return user_id, role


def require_auth(roles=None):
    """Decorator: validate auth headers; if `roles` is set, restrict to those roles."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_user()
            g.user_id = user_id
            g.user_role = role
            if roles is not None and role not in roles:
                raise err("ERR_FORBIDDEN",
                          f"Role {role} not authorized for this operation")
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def get_pagination():
    """Read limit + offset query params per PRD §2.3."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    def _to_int(v, name):
        if v is None:
            return None
        # Reject non-integer strings explicitly
        try:
            i = int(v)
            # Disallow values like "1.5" or "abc" — Python's int() catches those
            # but float-shaped "1.5" → ValueError already. Disallow whitespace.
            if str(v).strip() != str(i):
                raise ValueError
            return i
        except (TypeError, ValueError):
            raise err("ERR_INVALID_PAGINATION",
                      f"{name} must be an integer")

    limit = _to_int(raw_limit, "limit")
    offset = _to_int(raw_offset, "offset")
    if limit is None:
        limit = 10
    if offset is None:
        offset = 0
    if limit < 1 or limit > 100:
        raise err("ERR_INVALID_PAGINATION", "limit out of range [1,100]")
    if offset < 0:
        raise err("ERR_INVALID_PAGINATION", "offset must be non-negative")
    return limit, offset


def get_json_body() -> dict:
    """Return the JSON body or {} (and raise on malformed JSON)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False)
    except Exception:
        raise err("ERR_VALIDATION", "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return body
