"""Request-body well-formedness helpers (ERR_INVALID_REQUEST, 400).

These are the lowest-priority validation (PRD 2.8): malformed payloads. They run
after the structural gates (auth, ownership, existence, state) in each route by
virtue of being invoked only once those checks have passed.
"""
from flask import request

from errors import err


def require_body():
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def optional_body():
    """For action endpoints with no required body; tolerate empty/missing."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def require_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v.strip() == "":
        raise err("ERR_INVALID_REQUEST", "Field %s is required and must be a non-empty string" % key)
    return v


def require_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (key, sorted(allowed)))
    return v


def require_int(body, key, minimum=None):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s is required and must be an integer" % key)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (key, minimum))
    return v


def opt_int(body, key, default=None, minimum=None):
    if key not in body or body.get(key) is None:
        return default
    return require_int(body, key, minimum=minimum)


def opt_bool(body, key, default):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % key)
    return v


def opt_str(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % key)
    return v
