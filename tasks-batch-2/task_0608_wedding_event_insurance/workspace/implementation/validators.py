"""Request body parsing and field validation helpers.

A malformed body, a missing required field, a type mismatch, or an invalid enum
value is rejected with ERR_INVALID_REQUEST (PRD §3.10).
"""
from flask import request

from errors import err
from response import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
    PAGE_OFFSET_MIN,
)


def get_body():
    """Return the JSON body as a dict, or {} for an empty body.

    Raises ERR_INVALID_REQUEST when the body is present but not a JSON object.
    """
    if request.content_length in (None, 0):
        data = None
    else:
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def req_str(body, name):
    if name not in body:
        raise err("ERR_INVALID_REQUEST", "missing required field: %s" % name)
    val = body[name]
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "%s must be a non-empty string" % name)
    return val


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string" % name)
    return val


def req_enum(body, name, choices):
    val = req_str(body, name)
    if val not in choices:
        raise err("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, sorted(choices)))
    return val


def opt_enum(body, name, choices, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str) or val not in choices:
        raise err("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, sorted(choices)))
    return val


def _is_int(val):
    # bool is a subclass of int; reject it as a numeric.
    return isinstance(val, int) and not isinstance(val, bool)


def req_int(body, name, minimum=None, maximum=None):
    if name not in body:
        raise err("ERR_INVALID_REQUEST", "missing required field: %s" % name)
    val = body[name]
    if not _is_int(val):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minimum))
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maximum))
    return val


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def req_number(body, name, gt=None, ge=None, le=None):
    """Require a numeric value (int or float)."""
    if name not in body:
        raise err("ERR_INVALID_REQUEST", "missing required field: %s" % name)
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err("ERR_INVALID_REQUEST", "%s must be a number" % name)
    if gt is not None and not val > gt:
        raise err("ERR_INVALID_REQUEST", "%s must be > %s" % (name, gt))
    if ge is not None and not val >= ge:
        raise err("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, ge))
    if le is not None and not val <= le:
        raise err("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, le))
    return val


def req_bool(body, name):
    if name not in body:
        raise err("ERR_INVALID_REQUEST", "missing required field: %s" % name)
    val = body[name]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return val


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return val


def get_pagination():
    """Parse limit/offset query params (PRD §2.3). Returns (limit, offset)."""
    limit = _parse_query_int("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _parse_query_int("offset", PAGE_OFFSET_DEFAULT, PAGE_OFFSET_MIN, None)
    return limit, offset


def _parse_query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minimum))
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maximum))
    return val


def query_str(name):
    return request.args.get(name)
