"""Request body well-formedness validation (validation priority 3)."""
from util import ApiError, parse_date, parse_datetime


def body_json():
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % name)
    return body[name]


def opt_field(body, name, default=None):
    v = body.get(name, default)
    return default if v is None else v


def as_str(body, name, required=True, allow_empty=False):
    if name not in body or body[name] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % name)
        return None
    v = body[name]
    if not isinstance(v, str) or (not allow_empty and not v):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be a non-empty string" % name)
    return v


def as_int(body, name, required=True, lo=None, hi=None, default=None):
    if name not in body or body[name] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % name)
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be an integer" % name)
    if lo is not None and v < lo:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s out of range" % name)
    if hi is not None and v > hi:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s out of range" % name)
    return v


def as_bool(body, name, required=False, default=False):
    if name not in body or body[name] is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: %s" % name)
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be a boolean" % name)
    return v


def as_enum(body, name, allowed, required=True):
    v = as_str(body, name, required=required)
    if v is None:
        return None
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s has invalid value" % name)
    return v


def as_date(body, name, required=True):
    v = as_str(body, name, required=required)
    if v is None:
        return None
    try:
        parse_date(v)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field %s must be an ISO date (YYYY-MM-DD)" % name)
    return v
