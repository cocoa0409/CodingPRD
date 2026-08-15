"""Request-body well-formedness helpers (PRD §2.9 step 3)."""

import re

from flask import request

import db
from errors import ApiError, ERR_INVALID_REQUEST

_SERVICE_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def body():
    """Return the JSON request body as a dict, or raise ERR_INVALID_REQUEST."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_bool(v):
    return isinstance(v, bool)


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           f"Missing required field: {f}")


def reject_unknown_fields(data, allowed):
    for k in data:
        if k not in allowed:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Unknown field: {k}")


def req_string(data, field, required=True, allow_empty=False):
    if field not in data or data[field] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           f"Missing required field: {field}")
        return None
    v = data[field]
    if not isinstance(v, str) or (not allow_empty and v == ""):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be a non-empty string")
    return v


def req_int(data, field, required=True, minimum=None, default=None):
    if field not in data or data[field] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           f"Missing required field: {field}")
        return default
    v = data[field]
    if not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be >= {minimum}")
    return v


def req_positive_cents(data, field, required=True):
    """Integer cents field declared > 0."""
    if field not in data or data[field] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           f"Missing required field: {field}")
        return None
    v = data[field]
    if not _is_int(v) or v <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be an integer > 0")
    return v


def req_bool(data, field, default):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not _is_bool(v):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be a boolean")
    return v


def req_enum(data, field, values, required=True, default=None):
    if field not in data or data[field] is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           f"Missing required field: {field}")
        return default
    v = data[field]
    if v not in values:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be one of {sorted(values)}")
    return v


def req_service_month(data, field="service_month"):
    v = req_string(data, field)
    if not _SERVICE_MONTH_RE.match(v):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must match YYYY-MM")
    return v


def req_datetime(data, field, required=True):
    v = req_string(data, field, required=required)
    if v is None:
        return None
    try:
        db.parse_iso(v)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be an ISO 8601 timestamp")
    return v


def opt_string(data, field, default=""):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be a string")
    return v


def opt_enum(data, field, values, default=""):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if v not in values:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be one of {sorted(values)}")
    return v
