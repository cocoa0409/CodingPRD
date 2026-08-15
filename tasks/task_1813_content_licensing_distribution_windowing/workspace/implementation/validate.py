"""Request-body schema validation helpers (priority-3 ERR_INVALID_REQUEST)."""
from flask import request

from errors import err, ERR_INVALID_REQUEST
from util import parse_dt


def json_body(required: bool = True) -> dict:
    """Parse the JSON body. For required bodies, must be a JSON object."""
    body = request.get_json(silent=True)
    if body is None:
        if required:
            err(ERR_INVALID_REQUEST, "request body must be a JSON object")
        return {}
    if not isinstance(body, dict):
        if required:
            err(ERR_INVALID_REQUEST, "request body must be a JSON object")
        return {}
    return body


def _missing(body, name):
    return name not in body or body[name] is None


def field_str(body, name, required=True, default=None):
    if _missing(body, name):
        if required:
            err(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, str) or isinstance(v, bool):
        err(ERR_INVALID_REQUEST, f"field {name} must be a string")
    return v


def field_int(body, name, required=True, default=None):
    if _missing(body, name):
        if required:
            err(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        err(ERR_INVALID_REQUEST, f"field {name} must be an integer")
    return v


def field_num(body, name, required=True, default=None):
    if _missing(body, name):
        if required:
            err(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err(ERR_INVALID_REQUEST, f"field {name} must be a number")
    return v


def field_bool(body, name, required=True, default=None):
    if _missing(body, name):
        if required:
            err(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, bool):
        err(ERR_INVALID_REQUEST, f"field {name} must be a boolean")
    return v


def field_arr(body, name, required=True, default=None, min_len=None, elem_str=False):
    if _missing(body, name):
        if required:
            err(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, list):
        err(ERR_INVALID_REQUEST, f"field {name} must be an array")
    if min_len is not None and len(v) < min_len:
        err(ERR_INVALID_REQUEST, f"field {name} must contain at least {min_len} element(s)")
    if elem_str and any(not isinstance(x, str) for x in v):
        err(ERR_INVALID_REQUEST, f"field {name} must contain only strings")
    return v


def field_dt(body, name, required=True, default=None):
    if _missing(body, name):
        if required:
            err(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, str):
        err(ERR_INVALID_REQUEST, f"field {name} must be an ISO 8601 datetime string")
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        err(ERR_INVALID_REQUEST, f"field {name} is not a valid ISO 8601 datetime")


def field_enum(body, name, values, required=True, default=None):
    if _missing(body, name):
        if required:
            err(ERR_INVALID_REQUEST, f"missing required field: {name}")
        return default
    v = body[name]
    if not isinstance(v, str) or v not in values:
        err(ERR_INVALID_REQUEST, f"field {name} must be one of {sorted(values)}")
    return v


def check_window_order(start, end, label="window"):
    """Any window or period end must be strictly after its start (schema rule)."""
    if start is not None and end is not None and end <= start:
        err(ERR_INVALID_REQUEST, f"{label} end must be strictly after its start")
