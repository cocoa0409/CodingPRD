"""Shared request-shape validation helpers (rung 3: ERR_INVALID_REQUEST)."""

import db as _db
from db import parse_date
from errors import err_invalid_request


def body():
    from flask import request
    if not request.is_json:
        raise err_invalid_request("Request body must be JSON")
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def reject_unknown(data, allowed):
    for k in data.keys():
        if k not in allowed:
            raise err_invalid_request(f"Unknown field: {k}")


def require(data, field):
    v = data.get(field)
    if v is None:
        raise err_invalid_request(f"Missing required field: {field}")
    return v


def as_str(data, field, required=True):
    v = data.get(field)
    if v is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return None
    if not isinstance(v, str) or not v:
        raise err_invalid_request(f"{field} must be a non-empty string")
    return v


def as_int(data, field, required=True, min_value=None, max_value=None):
    v = data.get(field)
    if v is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{field} must be an integer")
    if min_value is not None and v < min_value:
        raise err_invalid_request(f"{field} must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise err_invalid_request(f"{field} must be <= {max_value}")
    return v


def as_bool(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise err_invalid_request(f"{field} must be a boolean")
    return v


def as_enum(data, field, choices, required=True):
    v = data.get(field)
    if v is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return None
    if not isinstance(v, str) or v not in choices:
        raise err_invalid_request(f"{field} must be one of {sorted(choices)}")
    return v


def as_date(data, field, required=True):
    v = data.get(field)
    if v is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return None
    try:
        d = parse_date(v)
    except (ValueError, TypeError):
        raise err_invalid_request(f"{field} must be a YYYY-MM-DD date")
    return v  # return the canonical string form


def as_date_value(s):
    return parse_date(s)


def as_number(data, field, required=False):
    v = data.get(field)
    if v is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_invalid_request(f"{field} must be a number")
    return v


def as_list(data, field, required=True, non_empty=False):
    v = data.get(field)
    if v is None:
        if required:
            raise err_invalid_request(f"Missing required field: {field}")
        return None
    if not isinstance(v, list):
        raise err_invalid_request(f"{field} must be a list")
    if non_empty and not v:
        raise err_invalid_request(f"{field} must be a non-empty list")
    return v


def validate_no_future_date(date_str, field):
    from errors import err_invalid_request as eir
    try:
        d = parse_date(date_str)
    except (ValueError, TypeError):
        raise eir(f"{field} must be a YYYY-MM-DD date")
    if d > _db.today():
        raise eir(f"{field} may not be after today")
    return date_str
