"""Auth header extraction, role checking, and request-body field validators."""
from flask import request, g

from db import parse_dt, parse_date
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_VALIDATION_FAILED,
)

ROLES = ("AirportManager", "ArffChief", "SafetyOfficer", "FaaInspector", "Firefighter")
ALL_ROLES = list(ROLES)


def authenticate():
    uid = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not uid or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and name a declared role",
        )
    g.user_id = uid
    g.user_role = role


def require(roles):
    if g.user_role not in roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Role is not permitted for this endpoint",
        )


def json_body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _fail(name):
    raise ApiError(
        ERR_VALIDATION_FAILED, 400,
        f"Required body field '{name}' is missing or has the wrong type",
    )


def need_str(data, name, nonempty=False):
    v = data.get(name)
    if not isinstance(v, str) or (nonempty and v == ""):
        _fail(name)
    return v


def need_number(data, name, min_value=None, exclusive_min=False):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _fail(name)
    if min_value is not None:
        if exclusive_min and not v > min_value:
            _fail(name)
        if not exclusive_min and not v >= min_value:
            _fail(name)
    return v


def need_int(data, name, min_value=None):
    v = data.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        _fail(name)
    if min_value is not None and not v >= min_value:
        _fail(name)
    return v


def need_bool(data, name):
    v = data.get(name)
    if not isinstance(v, bool):
        _fail(name)
    return v


def need_enum(data, name, allowed):
    v = data.get(name)
    if not isinstance(v, str) or v not in allowed:
        _fail(name)
    return v


def need_date_str(data, name):
    v = data.get(name)
    if parse_date(v) is None:
        _fail(name)
    return v


def need_datetime_str(data, name):
    v = data.get(name)
    if parse_dt(v) is None:
        _fail(name)
    return v


def opt_str(data, name, current, nonempty=False):
    if name not in data:
        return current
    return need_str(data, name, nonempty=nonempty)


def opt_number(data, name, current, min_value=None, exclusive_min=False):
    if name not in data:
        return current
    return need_number(data, name, min_value=min_value, exclusive_min=exclusive_min)


def opt_int(data, name, current, min_value=None):
    if name not in data:
        return current
    return need_int(data, name, min_value=min_value)


def opt_bool(data, name, current):
    if name not in data:
        return current
    return need_bool(data, name)
