"""Request-body parsing/validation helpers.

Malformed bodies (missing required fields, bad enum, out-of-range numbers) raise
ERR_INVALID_REQUEST (400) per PRD §3.8. Semantic failures not covered by a more
specific code raise ERR_VALIDATION (422) at the call site.
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


def req_datetime(body, field):
    v = require(body, field)
    try:
        return parse_iso8601(v)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 datetime.")


def opt_datetime(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    try:
        return parse_iso8601(body[field])
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 datetime.")


def req_str_list_subset(body, field, choices, default=None):
    """Optional array field; each element must be in choices."""
    if field not in body or body[field] is None:
        return list(default) if default is not None else []
    v = body[field]
    if not isinstance(v, list):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an array.")
    for item in v:
        if not isinstance(item, str) or item not in choices:
            raise err("ERR_INVALID_REQUEST",
                      f"{field} elements must each be one of {sorted(choices)}.")
    return v


# ---- pagination ----

def pagination_params():
    """Parse limit/offset per PRD §2.3 (limit default 10, 1..100; offset default 0)."""
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
