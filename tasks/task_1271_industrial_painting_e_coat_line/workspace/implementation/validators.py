"""Request body well-formedness helpers (guard rung 3, PRD SS2.6)."""
from datetime import datetime, timezone
from decimal import Decimal

from flask import request

from errors import ApiError


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def req(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % name)
    return body[name]


def as_str(v, name):
    if not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be a non-empty string" % name)
    return v


def as_int(v, name):
    if isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % name)
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % name)


def as_num(v, name):
    """Numeric field; returned as exact Decimal(str(value))."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be a number" % name)
    return Decimal(str(v))


def as_dt(v, name):
    """ISO 8601 datetime string -> aware UTC datetime. Naive values assumed UTC."""
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be an ISO 8601 datetime string" % name)
    t = v.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be an ISO 8601 datetime string" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
