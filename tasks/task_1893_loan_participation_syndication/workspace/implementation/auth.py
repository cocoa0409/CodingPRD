"""Auth context extraction and validation helpers (PRD sections 2.1, 2.9)."""
import functools

from flask import request

import errors

VALID_ROLES = {"AgentBank", "Borrower", "ParticipantLender", "System"}


def caller():
    """Return (user_id, role); raises on missing/empty headers.

    A role value outside the four recognized roles, or System, is simply not
    permitted on any endpoint and fails the role check with 403.
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or not uid.strip() or not role.strip():
        raise errors.missing_context()
    return uid, role


def require_roles(*roles):
    """Decorator enforcing priority 1 (headers) and 2 (role permission)."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = caller()
            if role not in roles:
                raise errors.forbidden_role()
            return fn(uid, role, *args, **kwargs)

        return wrapper

    return deco


def body():
    """JSON body of the request; {} when absent, error when malformed."""
    from flask import request as req

    if req.data is None or req.data == b"":
        return {}
    data = req.get_json(silent=True, force=True)
    if data is None or not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data


# --- field validators (priority 5 request shape) ----------------------------

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v.strip():
        raise errors.invalid_request(f"Field '{field}' is required")
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if not is_int(v):
        raise errors.invalid_request(f"Field '{field}' must be an integer")
    if minimum is not None and v < minimum:
        raise errors.invalid_request(f"Field '{field}' is out of range")
    return v


def opt_int(data, field, default):
    v = data.get(field)
    if v is None:
        return default
    if not is_int(v):
        raise errors.invalid_request(f"Field '{field}' must be an integer")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise errors.invalid_request(f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def req_date(data, field):
    from store import parse_date

    v = data.get(field)
    try:
        d = parse_date(v)
    except (ValueError, AttributeError):
        raise errors.invalid_request(f"Field '{field}' must be an ISO date")
    return v, d
