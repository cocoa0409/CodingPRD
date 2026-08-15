"""Auth header extraction, RBAC decorator, pagination and body validators."""
from functools import wraps

from flask import g, request

from db import parse_dt
from errors import bad_request, err

ROLES = [
    "IntegrityAnalyst",
    "FieldTechnician",
    "ComplianceOfficer",
    "DispatchCoordinator",
    "CalibrationTech",
]


def require_roles(*allowed):
    """401 ERR_UNAUTHENTICATED when headers missing/invalid; 403 otherwise."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise err("ERR_UNAUTHENTICATED",
                          "Missing or invalid X-User-Role / X-User-ID headers", 401)
            if role not in allowed:
                raise err("ERR_FORBIDDEN",
                          "Role not permitted to invoke this endpoint", 403)
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise bad_request("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise bad_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise bad_request("limit must be between 1 and 100")
    if offset < 0:
        raise bad_request("offset must be >= 0")
    return limit, offset


def parse_bool_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise bad_request(f"{name} must be a boolean")


# --- request body helpers -------------------------------------------------

def body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data


def opt_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object")
    return data


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(d, name):
    v = d.get(name)
    if not isinstance(v, str) or v == "":
        raise bad_request(f"{name} is required and must be a string")
    return v


def req_num(d, name):
    v = d.get(name)
    if not _is_num(v):
        raise bad_request(f"{name} is required and must be a number")
    return v


def req_int(d, name):
    v = d.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise bad_request(f"{name} is required and must be an integer")
    return v


def req_bool(d, name):
    v = d.get(name)
    if not isinstance(v, bool):
        raise bad_request(f"{name} is required and must be a boolean")
    return v


def req_dt(d, name):
    v = d.get(name)
    dt = parse_dt(v)
    if dt is None:
        raise bad_request(f"{name} is required and must be an ISO 8601 datetime")
    return dt


def req_enum(d, name, allowed):
    v = d.get(name)
    if v not in allowed:
        raise bad_request(f"{name} must be one of {sorted(allowed)}")
    return v


def req_list(d, name):
    v = d.get(name)
    if not isinstance(v, list):
        raise bad_request(f"{name} is required and must be an array")
    return v
