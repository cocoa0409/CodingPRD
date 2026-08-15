"""Auth header extraction, role checking, and request body field validation."""
from decimal import Decimal
from functools import wraps

from flask import g, request

from errors import (
    ApiError,
    ERR_AUTH,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
)

ROLES = ("Grower", "Chef", "OpsManager")


def require_roles(*allowed):
    """Priority 1 (headers) then priority 2 (role permission)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID", "")
            role = request.headers.get("X-User-Role", "")
            if not isinstance(uid, str) or not uid.strip() or role not in ROLES:
                raise ApiError(
                    400,
                    ERR_AUTH,
                    "X-User-ID and X-User-Role headers must be present and valid.",
                )
            if allowed and role not in allowed:
                raise ApiError(
                    403, ERR_FORBIDDEN, "Role not permitted for this operation."
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(400, ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def _missing(name):
    raise ApiError(400, ERR_INVALID_REQUEST, f"Missing required field: {name}.")


def _bad_type(name):
    raise ApiError(400, ERR_INVALID_REQUEST, f"Field has wrong type: {name}.")


def req_field(body, name):
    if name not in body or body[name] is None:
        _missing(name)
    return body[name]


def as_str(value, name):
    if not isinstance(value, str):
        _bad_type(name)
    return value


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad_type(name)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        _bad_type(name)
    return value


def as_num(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad_type(name)
    return Decimal(str(value))


def req_str(body, name):
    return as_str(req_field(body, name), name)


def req_int(body, name):
    return as_int(req_field(body, name), name)


def req_bool(body, name):
    return as_bool(req_field(body, name), name)


def req_num(body, name):
    return as_num(req_field(body, name), name)


def opt_str(body, name):
    if name not in body or body[name] is None:
        return None
    return as_str(body[name], name)


def opt_int(body, name):
    if name not in body or body[name] is None:
        return None
    return as_int(body[name], name)


def parse_pagination():
    """limit: default 10, min 1, max 100; offset: default 0. Out-of-range clamps."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError(400, ERR_INVALID_REQUEST, "limit must be an integer.")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(400, ERR_INVALID_REQUEST, "offset must be an integer.")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset
