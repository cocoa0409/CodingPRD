"""Request-shape integrity helpers (validation priority 3)."""
from errors import ApiError, ERR_VALIDATION_FAILED


def _fail(msg):
    raise ApiError(ERR_VALIDATION_FAILED, msg, 400)


def get_json_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        _fail("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            _fail(f"Missing required field: {f}")


def reject_unknown_fields(body, allowed):
    """Client-supplied computed/system fields are rejected; anything not declared is rejected."""
    for k in body:
        if k not in allowed:
            _fail(f"Field not allowed: {k}")


def validate_enum(body, field, members, required=True):
    if field not in body or body[field] is None:
        if required:
            _fail(f"Missing required field: {field}")
        return
    if body[field] not in members:
        _fail(f"Invalid value for {field}: {body[field]}")


def validate_string(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            _fail(f"Missing required field: {field}")
        return
    if not isinstance(body[field], str):
        _fail(f"Field {field} must be a string")


def validate_int(body, field, required=True, min_val=None, max_val=None):
    if field not in body or body[field] is None:
        if required:
            _fail(f"Missing required field: {field}")
        return
    v = body[field]
    if not isinstance(v, int) or isinstance(v, bool):
        _fail(f"Field {field} must be an integer")
    if min_val is not None and v < min_val:
        _fail(f"Field {field} must be >= {min_val}")
    if max_val is not None and v > max_val:
        _fail(f"Field {field} must be <= {max_val}")


def validate_bool(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            _fail(f"Missing required field: {field}")
        return
    if not isinstance(body[field], bool):
        _fail(f"Field {field} must be a boolean")


def validate_datetime(body, field, required=True):
    from services.clock import parse_iso
    if field not in body or body[field] is None:
        if required:
            _fail(f"Missing required field: {field}")
        return None
    v = body[field]
    if not isinstance(v, str):
        _fail(f"Field {field} must be an ISO8601 string")
    try:
        return parse_iso(v)
    except Exception:
        _fail(f"Field {field} is not a valid ISO8601 timestamp")


def validate_day_date(body, field, required=True):
    import re
    if field not in body or body[field] is None:
        if required:
            _fail(f"Missing required field: {field}")
        return
    v = body[field]
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        _fail(f"Field {field} must be a YYYY-MM-DD date string")
