"""Request-body field validation (ERR_INVALID_REQUEST / ERR_VALIDATION)."""
from errors import err

INVALID = "ERR_INVALID_REQUEST"


def get_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(INVALID, "Request body must be a JSON object")
    return body


def require(body, name):
    if name not in body or body[name] is None:
        raise err(INVALID, "Missing required field: %s" % name)
    return body[name]


def _is_bool(v):
    return isinstance(v, bool)


def _is_int(v):
    # bools are ints in python; exclude them
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, name, allow_empty=False):
    v = require(body, name)
    if not isinstance(v, str):
        raise err(INVALID, "Field %s must be a string" % name)
    if not allow_empty and v == "":
        raise err(INVALID, "Field %s must be non-empty" % name)
    return v


def opt_str(body, name, default=None, allow_empty=True):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err(INVALID, "Field %s must be a string" % name)
    if not allow_empty and v == "":
        raise err(INVALID, "Field %s must be non-empty" % name)
    return v


def req_int(body, name, minimum=None):
    v = require(body, name)
    if not _is_int(v):
        raise err(INVALID, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise err(INVALID, "Field %s must be >= %s" % (name, minimum))
    return v


def opt_int(body, name, default=None, minimum=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not _is_int(v):
        raise err(INVALID, "Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise err(INVALID, "Field %s must be >= %s" % (name, minimum))
    return v


def req_number(body, name, minimum=None, maximum=None):
    v = require(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(INVALID, "Field %s must be a number" % name)
    if minimum is not None and v < minimum:
        raise err(INVALID, "Field %s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        raise err(INVALID, "Field %s must be <= %s" % (name, maximum))
    return v


def req_bool(body, name):
    v = require(body, name)
    if not _is_bool(v):
        raise err(INVALID, "Field %s must be a boolean" % name)
    return v


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not _is_bool(v):
        raise err(INVALID, "Field %s must be a boolean" % name)
    return v


def req_enum(body, name, allowed):
    v = require(body, name)
    if not isinstance(v, str) or v not in allowed:
        raise err(INVALID, "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str) or v not in allowed:
        raise err(INVALID, "Field %s must be one of %s" % (name, sorted(allowed)))
    return v


def req_datetime(body, name):
    from clock import parse_iso
    v = require(body, name)
    if not isinstance(v, str):
        raise err(INVALID, "Field %s must be an ISO 8601 datetime string" % name)
    try:
        return parse_iso(v)
    except ValueError:
        raise err(INVALID, "Field %s must be a valid ISO 8601 datetime" % name)
