"""Body field-validation helpers (priority-6 tier, ERR_INVALID_REQUEST; and the
semantic priority-22 tier, ERR_VALIDATION). See PRD §3.6, §3.8.
"""
from errors import err


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return v


def require_int(body, field):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return v


def require_number(body, field):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a number" % field)
    return v


def require_enum(body, field, allowed):
    v = require(body, field)
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def optional_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return v


def optional_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return v
