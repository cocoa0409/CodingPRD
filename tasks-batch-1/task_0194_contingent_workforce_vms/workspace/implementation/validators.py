"""Field-level request-body validation helpers (ERR_INVALID_REQUEST, last in priority)."""
from errors import err


def require_present(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def as_string(value, field):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "%s must be a non-empty string" % field)
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", "%s must be a number" % field)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be a boolean" % field)
    return value


def positive_int(value, field):
    v = as_int(value, field)
    if v < 1:
        raise err("ERR_INVALID_REQUEST", "%s must be >= 1" % field)
    return v


def non_negative_int(value, field):
    v = as_int(value, field)
    if v < 0:
        raise err("ERR_INVALID_REQUEST", "%s must be >= 0" % field)
    return v


def hours_in_range(value, field):
    v = as_number(value, field)
    if v < 0 or v > 168:
        raise err("ERR_INVALID_REQUEST", "%s must be within [0, 168]" % field)
    return v


def markup_in_range(value, field):
    v = as_number(value, field)
    if v < 0 or v > 2.0:
        raise err("ERR_INVALID_REQUEST", "%s must be within [0, 2.0]" % field)
    return v


def enum_member(value, field, allowed):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "%s must be one of %s" % (field, sorted(allowed)))
    return value
