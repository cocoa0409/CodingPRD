"""Request-shape validation helpers (priority 3: ERR_INVALID_REQUEST)."""

from decimal import Decimal, InvalidOperation

import dates
import errors


def get_json_body(required=False):
    from flask import request

    body = request.get_json(silent=True)
    if body is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "Request body must be JSON")
        return {}
    if not isinstance(body, dict):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def check_fields(body, required, optional):
    """Ensure all required fields present, and no unknown fields appear."""
    allowed = set(required) | set(optional)
    for key in body:
        if key not in allowed:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Unknown field: {key}")
    for key in required:
        if key not in body or body[key] is None:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {key}")


def req_string(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return None
    if not isinstance(v, str) or v == "":
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"Field {name} must be a non-empty string")
    return v


def req_enum(body, name, values, required=True, default=None):
    v = body.get(name)
    if v is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    if not isinstance(v, str) or v not in values:
        errors.raise_error(
            errors.ERR_INVALID_REQUEST, f"Field {name} must be one of {sorted(values)}"
        )
    return v


def req_int(body, name, required=True, default=None, minimum=None):
    v = body.get(name)
    if v is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"Field {name} must be >= {minimum}")
    return v


def req_number(body, name, required=True, default=None):
    v = body.get(name)
    if v is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"Field {name} must be a number")
    try:
        return Decimal(str(v))
    except InvalidOperation:
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"Field {name} must be a number")


def req_array(body, name, required=True, default=None, element_type=str):
    v = body.get(name)
    if v is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    if not isinstance(v, list):
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"Field {name} must be an array")
    for item in v:
        if not isinstance(item, element_type):
            errors.raise_error(
                errors.ERR_INVALID_REQUEST, f"Field {name} must contain {element_type.__name__}s"
            )
    return v


def req_datetime(body, name, required=True, default=None):
    """Validate an ISO datetime string; returns the ORIGINAL string (stored as given)."""
    v = body.get(name)
    if v is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    if dates.parse_datetime(v) is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 datetime")
    return v


def req_date(body, name, required=True, default=None):
    v = body.get(name)
    if v is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    if dates.parse_date(v) is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"Field {name} must be an ISO 8601 date")
    return v


def req_bool(body, name, required=True, default=None):
    v = body.get(name)
    if v is None:
        if required:
            errors.raise_error(errors.ERR_INVALID_REQUEST, f"Missing required field: {name}")
        return default
    if not isinstance(v, bool):
        errors.raise_error(errors.ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return v


def parse_pagination():
    """Parse limit/offset query params with defaults (scaffold §1.0)."""
    from flask import request

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset
