"""Input parsing/validation helpers. All bad input -> ERR_INVALID_REQUEST (400)."""

import errors
from errors import ApiError
from clock import parse_iso, parse_date


def bad(msg):
    return ApiError(errors.ERR_INVALID_REQUEST, 400, msg)


def get_body():
    from flask import request

    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise bad("Request body must be a JSON object.")
    return body


def require_str(body, field, min_len=None):
    if field not in body:
        raise bad(f"Missing required field: {field}")
    value = body[field]
    if not isinstance(value, str):
        raise bad(f"Field {field} must be a string.")
    if min_len is not None and len(value) < min_len:
        raise bad(f"Field {field} must be at least {min_len} characters.")
    return value


def require_int(body, field, minimum=None, maximum=None):
    if field not in body:
        raise bad(f"Missing required field: {field}")
    value = body[field]
    # Reject booleans (which are ints in Python) and non-integers.
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad(f"Field {field} must be an integer.")
    if minimum is not None and value < minimum:
        raise bad(f"Field {field} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise bad(f"Field {field} must be <= {maximum}.")
    return value


def require_enum(body, field, choices):
    value = require_str(body, field)
    if value not in choices:
        raise bad(f"Field {field} must be one of {sorted(choices)}.")
    return value


def require_bool(body, field, default=None):
    if field not in body:
        if default is None:
            raise bad(f"Missing required field: {field}")
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise bad(f"Field {field} must be a boolean.")
    return value


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise bad(f"Field {field} must be a boolean.")
    return value


def require_iso_datetime(body, field):
    value = require_str(body, field)
    try:
        return parse_iso(value)
    except Exception:
        raise bad(f"Field {field} must be an ISO 8601 datetime.")


def require_iso_date(body, field):
    value = require_str(body, field)
    try:
        parse_date(value)
    except Exception:
        raise bad(f"Field {field} must be an ISO date YYYY-MM-DD.")
    return value
