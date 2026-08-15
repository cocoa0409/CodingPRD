"""Auth header extraction, role gating, body/field validation, pagination."""
from functools import wraps

from flask import g, request

from errors import (ApiError, ERR_HEADERS, ERR_INVALID_REQUEST, ERR_ROLE)

ROLES = {"District504Director", "Section504Coordinator", "Teacher", "SchoolPrincipal", "Parent"}

ALL_ROLES = ("District504Director", "Section504Coordinator", "Teacher", "SchoolPrincipal", "Parent")


def require_roles(*roles):
    """Priority 1: headers present + well-formed. Priority 2: role authorized."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if uid is None or role is None or not str(uid).strip() or role not in ROLES:
                raise ApiError(ERR_HEADERS[0], ERR_HEADERS[1],
                               "X-User-ID and X-User-Role headers must be present and well-formed")
            if role not in roles:
                raise ApiError(ERR_ROLE[0], ERR_ROLE[1],
                               f"Role {role} is not authorized for this operation")
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def body():
    """JSON object body; absent body treated as {} (transition endpoints take none)."""
    d = request.get_json(silent=True)
    if d is None:
        return {}
    if not isinstance(d, dict):
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1],
                       "Request body must be a JSON object")
    return d


def _bad(field, msg):
    raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], f"Field '{field}': {msg}")


def req_field(d, name):
    if name not in d or d[name] is None:
        _bad(name, "is required")
    return d[name]


def req_str(d, name):
    v = req_field(d, name)
    if not isinstance(v, str) or not v.strip():
        _bad(name, "must be a non-empty string")
    return v


def opt_str(d, name, default=None):
    if name not in d or d[name] is None:
        return default
    v = d[name]
    if not isinstance(v, str):
        _bad(name, "must be a string")
    return v


def req_bool(d, name):
    v = req_field(d, name)
    if not isinstance(v, bool):
        _bad(name, "must be a boolean")
    return v


def opt_bool(d, name, default=False):
    if name not in d or d[name] is None:
        return default
    v = d[name]
    if not isinstance(v, bool):
        _bad(name, "must be a boolean")
    return v


def req_int(d, name):
    v = req_field(d, name)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(name, "must be an integer")
    return v


def req_enum(d, name, allowed):
    v = req_field(d, name)
    if not isinstance(v, str) or v not in allowed:
        _bad(name, f"must be one of {sorted(allowed)}")
    return v


def opt_enum(d, name, allowed, default=None):
    if name not in d or d[name] is None:
        return default
    return req_enum(d, name, allowed)


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be >= 0")
    return limit, offset


def parse_bool_filter(name):
    v = request.args.get(name)
    if v is None:
        return None
    lv = v.strip().lower()
    if lv == "true":
        return True
    if lv == "false":
        return False
    _bad(name, "must be 'true' or 'false'")
