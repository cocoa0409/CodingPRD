"""Request-body well-formedness helpers (PRD §2.10 step 3).

Unknown request fields — including client-supplied id/version/created_at —
are ignored, not rejected (PRD §2.5), so there is deliberately no
reject_unknown_fields helper here.
"""

from flask import request

import db
from errors import ApiError, ERR_INVALID_REQUEST


def body():
    """Return the JSON request body as a dict ({} when absent)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_bool(v):
    return isinstance(v, bool)


def _is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def _err(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def req_string(data, field, required=True, allow_empty=False):
    if field not in data or data[field] is None:
        if required:
            _err(f"Missing required field: {field}")
        return None
    v = data[field]
    if not isinstance(v, str) or (not allow_empty and v == ""):
        _err(f"Field {field} must be a non-empty string")
    return v


def opt_string(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        _err(f"Field {field} must be a string")
    return v


def req_int(data, field, required=True, minimum=None, default=None):
    if field not in data or data[field] is None:
        if required:
            _err(f"Missing required field: {field}")
        return default
    v = data[field]
    if not _is_int(v):
        _err(f"Field {field} must be an integer")
    if minimum is not None and v < minimum:
        _err(f"Field {field} must be >= {minimum}")
    return v


def req_positive_int(data, field, required=True):
    """Integer field declared > 0 (quantity / amount_cents / price)."""
    if field not in data or data[field] is None:
        if required:
            _err(f"Missing required field: {field}")
        return None
    v = data[field]
    if not _is_int(v) or v <= 0:
        _err(f"Field {field} must be an integer > 0")
    return v


def req_number(data, field, required=True, minimum=None, maximum=None,
               default=None):
    """Numeric field (support_rate_pct / future_license_discount_pct)."""
    if field not in data or data[field] is None:
        if required:
            _err(f"Missing required field: {field}")
        return default
    v = data[field]
    if not _is_number(v):
        _err(f"Field {field} must be a number")
    if minimum is not None and v < minimum:
        _err(f"Field {field} must be >= {minimum}")
    if maximum is not None and v > maximum:
        _err(f"Field {field} must be <= {maximum}")
    return v


def req_bool(data, field, default=None, required=False):
    if field not in data or data[field] is None:
        if required:
            _err(f"Missing required field: {field}")
        return default
    v = data[field]
    if not _is_bool(v):
        _err(f"Field {field} must be a boolean")
    return v


def req_enum(data, field, values, required=True, default=None):
    if field not in data or data[field] is None:
        if required:
            _err(f"Missing required field: {field}")
        return default
    v = data[field]
    if v not in values:
        _err(f"Field {field} must be one of {sorted(values)}")
    return v


def req_datetime(data, field, required=True):
    """Validate ISO 8601 parseability; return the raw input string."""
    v = req_string(data, field, required=required)
    if v is None:
        return None
    try:
        db.parse_iso(v)
    except (ValueError, TypeError):
        _err(f"Field {field} must be an ISO 8601 timestamp")
    return v


def req_str_array(data, field, required=True):
    """Non-empty array of string ids."""
    if field not in data or data[field] is None:
        if required:
            _err(f"Missing required field: {field}")
        return None
    v = data[field]
    if not isinstance(v, list) or len(v) == 0:
        _err(f"Field {field} must be a non-empty array")
    for item in v:
        if not isinstance(item, str):
            _err(f"Field {field} must contain only string ids")
    return v
