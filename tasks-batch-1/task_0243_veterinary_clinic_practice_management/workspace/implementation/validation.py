"""Request body / query validation helpers (PRD §1.4 priority 5, §2.3)."""
from datetime import datetime

import errors
from calculations import parse_dt


def get_json_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        errors.raise_err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}.")
    return body[field]


def require_str(body, field):
    value = require(body, field)
    if not isinstance(value, str) or value == "":
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a non-empty string.")
    return value


def require_enum(body, field, allowed):
    value = require(body, field)
    if value not in allowed:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be one of {sorted(allowed)}.")
    return value


def require_int(body, field, minimum=None):
    value = require(body, field)
    if isinstance(value, bool) or not isinstance(value, int):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be an integer.")
    if minimum is not None and value < minimum:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}.")
    return value


def optional_int(body, field, default=0, minimum=None):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be an integer.")
    if minimum is not None and value < minimum:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}.")
    return value


def require_number(body, field, gt=None, minimum=None):
    value = require(body, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a number.")
    if gt is not None and not (value > gt):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be > {gt}.")
    if minimum is not None and value < minimum:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}.")
    return value


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, bool):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be a boolean.")
    return value


def require_datetime(body, field):
    value = require(body, field)
    if not isinstance(value, str):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} must be an ISO 8601 string.")
    try:
        parse_dt(value)
    except Exception:
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Field {field} is not a valid ISO 8601 datetime.")
    return value


def parse_pagination():
    """limit defaults to 10 (min 1, max 100); offset defaults to 0 (PRD §2.3)."""
    from flask import request
    limit = _parse_query_int("limit", default=10, minimum=1, maximum=100)
    offset = _parse_query_int("offset", default=0, minimum=0, maximum=None)
    return limit, offset


def _parse_query_int(name, default, minimum, maximum):
    from flask import request
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        errors.raise_err(errors.ERR_INVALID_REQUEST, f"Query parameter {name} must be an integer.")
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value
