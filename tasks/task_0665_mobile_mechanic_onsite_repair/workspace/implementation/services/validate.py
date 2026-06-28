"""Shared structural-validation helpers (ERR_INVALID_REQUEST, priority 6)."""
from datetime import datetime, timezone

import errors
import db


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


def require_str(body, field):
    if field not in body:
        raise errors.invalid_request(f"Missing required field: {field}")
    val = body[field]
    if not isinstance(val, str) or val.strip() == "":
        raise errors.invalid_request(f"Field {field} must be a non-empty string.")
    return val


def require_int(body, field, minimum=None, exclusive_min=None):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}.")
    if exclusive_min is not None and val <= exclusive_min:
        raise errors.invalid_request(f"Field {field} must be > {exclusive_min}.")
    return val


def require_number(body, field, minimum=None, exclusive_min=None):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field {field} must be a number.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}.")
    if exclusive_min is not None and val <= exclusive_min:
        raise errors.invalid_request(f"Field {field} must be > {exclusive_min}.")
    return val


def optional_int(body, field, default=0, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {field} must be an integer.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}.")
    return val


def optional_number(body, field, default=0, minimum=None):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise errors.invalid_request(f"Field {field} must be a number.")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"Field {field} must be >= {minimum}.")
    return val


def require_enum(body, field, choices):
    if field not in body or body[field] is None:
        raise errors.invalid_request(f"Missing required field: {field}")
    val = body[field]
    if val not in choices:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(choices)}.")
    return val


def optional_enum(body, field, choices, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in choices:
        raise errors.invalid_request(f"Field {field} must be one of {sorted(choices)}.")
    return val


def parse_dt(value):
    """Parse an ISO-8601 datetime to a tz-aware UTC datetime, else ERR_INVALID_REQUEST."""
    if not isinstance(value, str) or value.strip() == "":
        raise errors.invalid_request("Datetime must be a non-empty ISO 8601 string.")
    try:
        return db._parse_iso(value)
    except (ValueError, TypeError):
        raise errors.invalid_request("Invalid ISO 8601 datetime.")
