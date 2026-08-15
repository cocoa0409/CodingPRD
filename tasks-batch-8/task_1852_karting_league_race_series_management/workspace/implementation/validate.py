"""Request-body validation helpers (validation priority 3: ERR_INVALID_REQUEST)."""
from flask import request

from errors import raise_error, ERR_INVALID_REQUEST
from util import parse_datetime, parse_date


def json_body():
    """Return the request JSON object; {} for an empty body, 400 for malformed."""
    data = request.get_json(silent=True)
    if data is None:
        raw = request.get_data() or b""
        if raw.strip():
            raise_error(ERR_INVALID_REQUEST, "request body is not valid JSON")
        return {}
    if not isinstance(data, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def _missing(body, name):
    return name not in body or body.get(name) is None


def v_str(body, name, required=True, default=None):
    if _missing(body, name):
        if required:
            raise_error(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, str) or not v.strip():
        raise_error(ERR_INVALID_REQUEST, f"field {name} must be a non-empty string")
    return v


def v_id(body, name, required=True, default=None):
    """Reference-id field: required string (emptiness tolerated; existence is tier 4)."""
    if _missing(body, name):
        if required:
            raise_error(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"field {name} must be a string id")
    return v


def v_int(body, name, required=True, default=None, min_val=None):
    if _missing(body, name):
        if required:
            raise_error(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if not is_int(v):
        raise_error(ERR_INVALID_REQUEST, f"field {name} must be an integer")
    if min_val is not None and v < min_val:
        raise_error(ERR_INVALID_REQUEST, f"field {name} must be >= {min_val}")
    return v


def v_num(body, name, required=True, default=None, gt=None):
    if _missing(body, name):
        if required:
            raise_error(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if not is_num(v):
        raise_error(ERR_INVALID_REQUEST, f"field {name} must be a number")
    if gt is not None and not (v > gt):
        raise_error(ERR_INVALID_REQUEST, f"field {name} must be > {gt}")
    return v


def v_bool(body, name, required=True, default=None):
    if _missing(body, name):
        if required:
            raise_error(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise_error(ERR_INVALID_REQUEST, f"field {name} must be a boolean")
    return v


def v_enum(body, name, allowed, required=True, default=None):
    if _missing(body, name):
        if required:
            raise_error(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise_error(
            ERR_INVALID_REQUEST,
            f"field {name} must be one of {sorted(allowed)}",
        )
    return v


def v_int_list(body, name, required=True, default=None):
    if _missing(body, name):
        if required:
            raise_error(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, list) or any(not is_int(x) for x in v):
        raise_error(ERR_INVALID_REQUEST, f"field {name} must be an array of integers")
    return v


def v_enum_list(body, name, allowed, required=True, default=None):
    if _missing(body, name):
        if required:
            raise_error(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, list) or any(not isinstance(x, str) or x not in allowed for x in v):
        raise_error(
            ERR_INVALID_REQUEST,
            f"field {name} must be an array drawn from {sorted(allowed)}",
        )
    return v


def v_datetime(body, name, required=True, default=None):
    """Validates and returns the raw string plus the parsed datetime."""
    if _missing(body, name):
        if required:
            raise_error(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default, None
    v = body[name]
    dt = parse_datetime(v)
    if dt is None:
        raise_error(ERR_INVALID_REQUEST, f"field {name} must be an ISO 8601 datetime")
    return v, dt


def v_date(body, name, required=True, default=None):
    if _missing(body, name):
        if required:
            raise_error(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default, None
    v = body[name]
    d = parse_date(v)
    if d is None:
        raise_error(ERR_INVALID_REQUEST, f"field {name} must be an ISO 8601 date (YYYY-MM-DD)")
    return v, d
