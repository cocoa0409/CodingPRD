"""Request-body parsing/validation helpers.

Missing required fields, bad enums, out-of-range numbers and malformed bodies
raise ERR_INVALID_REQUEST (HTTP 422 per PRD §5) at priority 5.
"""
from flask import request

from clock import parse_iso8601
from errors import err


def get_body():
    """Return the JSON body as a dict (empty dict when absent)."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Body must be a JSON object.")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}.")
    return body[field]


def as_str(value, field):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a string.")
    return value


def req_str(body, field):
    return as_str(require(body, field), field)


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return as_str(body[field], field)


def as_int(value, field):
    # Reject bools (which are ints in Python) and non-integers.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer.")
    return value


def req_int(body, field, minimum=None, maximum=None):
    v = as_int(require(body, field), field)
    _range_check(v, field, minimum, maximum)
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    v = as_int(body[field], field)
    _range_check(v, field, minimum, maximum)
    return v


def as_number(value, field):
    # Accept int or float (not bool); used for percentages and physical readings.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a number.")
    return value


def req_number(body, field, minimum=None, maximum=None):
    v = as_number(require(body, field), field)
    _range_check(v, field, minimum, maximum)
    return v


def opt_number(body, field, default=None, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    v = as_number(body[field], field)
    _range_check(v, field, minimum, maximum)
    return v


def _range_check(v, field, minimum, maximum):
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"{field} must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", f"{field} must be <= {maximum}.")


def req_enum(body, field, choices):
    v = require(body, field)
    if not isinstance(v, str) or v not in choices:
        raise err("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(choices)}.")
    return v


def opt_enum(body, field, choices, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str) or v not in choices:
        raise err("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(choices)}.")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", f"{field} must be a boolean.")
    return v


# ---- pagination (PRD §2.3) ----

def pagination_params():
    """Parse limit/offset (limit default 10, 1..100; offset default 0)."""
    args = request.args
    limit = _parse_int_param(args.get("limit"), "limit", default=10, minimum=1, maximum=100)
    offset = _parse_int_param(args.get("offset"), "offset", default=0, minimum=0, maximum=None)
    return limit, offset


def _parse_int_param(raw, name, default, minimum, maximum):
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"{name} must be an integer.")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"{name} must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", f"{name} must be <= {maximum}.")
    return v
