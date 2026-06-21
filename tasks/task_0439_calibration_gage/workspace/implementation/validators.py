"""Field-level validation helpers — ERR_INVALID_REQUEST (422), PRD §2.10 step.

These enforce: required fields present, well-typed, enum members valid, numeric
ranges (tolerances >= 0, counts within stated bounds).
"""
from errors import err


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "%s must be a non-empty string" % field)
    return v


def require_string_allow_empty(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string" % field)
    return v


def require_number(body, field):
    v = body.get(field)
    if not _is_number(v):
        raise err("ERR_INVALID_REQUEST", "%s must be a number" % field)
    return v


def require_int(body, field):
    v = body.get(field)
    if not _is_int(v):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  "%s must be one of %s" % (field, sorted(allowed)))
    return v


def require_nonneg_number(body, field):
    v = require_number(body, field)
    if v < 0:
        raise err("ERR_INVALID_REQUEST", "%s must be >= 0" % field)
    return v


def optional_number(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not _is_number(v):
        raise err("ERR_INVALID_REQUEST", "%s must be a number" % field)
    return v


def optional_int(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not _is_int(v):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    return v


def optional_string(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "%s must be a string" % field)
    return v
