"""Request body schema validation helpers (priority 4, ERR_INVALID_REQUEST)."""

from errors import raise_error, ERR_INVALID_REQUEST


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def req_string(body, field):
    v = body.get(field)
    if v is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if not isinstance(v, str) or not v:
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string")
    return v


def opt_string(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be a string")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if v not in allowed:
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_number(body, field, gt=None, ge=None, le=None):
    v = body.get(field)
    if v is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be a number")
    if gt is not None and not (v > gt):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be > {gt}")
    if ge is not None and not (v >= ge):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be >= {ge}")
    if le is not None and not (v <= le):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be <= {le}")
    return v


def opt_number(body, field):
    v = body.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be a number")
    return v


def req_int(body, field, gt=None, ge=None):
    v = body.get(field)
    if v is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be an integer")
    if gt is not None and not (v > gt):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be > {gt}")
    if ge is not None and not (v >= ge):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be >= {ge}")
    return v


def req_array(body, field):
    v = body.get(field)
    if v is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if not isinstance(v, list):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be an array")
    return v


def req_iso_datetime(body, field):
    from db import parse_iso
    v = body.get(field)
    if v is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 string")
    try:
        return parse_iso(v)
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} is not a valid ISO 8601 timestamp")


def req_date(body, field):
    from datetime import datetime
    v = body.get(field)
    if v is None:
        raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    if not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} must be a YYYY-MM-DD string")
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise_error(ERR_INVALID_REQUEST, f"Field {field} is not a valid YYYY-MM-DD date")
    return v
