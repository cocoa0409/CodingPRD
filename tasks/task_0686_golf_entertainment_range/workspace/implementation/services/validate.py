"""Request-body parsing and field validation helpers (PRD §2.6, §3).

These produce ERR_INVALID_REQUEST (400) for malformed bodies / bad types / bad
enums, and ERR_VALIDATION_RANGE (422) for numeric values outside an allowed
range (peak_demand_factor, negative amounts, negative shot points).
"""

from flask import request

from errors import raise_err, ERR_INVALID_REQUEST, ERR_VALIDATION_RANGE


def body():
    """Return the JSON body as a dict (empty dict when no body)."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def require(data, key, msg=None):
    if key not in data or data[key] is None:
        raise_err(ERR_INVALID_REQUEST, msg or ("missing required field: %s" % key))
    return data[key]


def as_str(value, key):
    if not isinstance(value, str) or value == "":
        raise_err(ERR_INVALID_REQUEST, "%s must be a non-empty string" % key)
    return value


def as_int(value, key):
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, "%s must be an integer" % key)
    return value


def as_number(value, key):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_err(ERR_INVALID_REQUEST, "%s must be a number" % key)
    return value


def as_bool(value, key):
    if not isinstance(value, bool):
        raise_err(ERR_INVALID_REQUEST, "%s must be a boolean" % key)
    return value


def as_enum(value, key, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise_err(ERR_INVALID_REQUEST, "%s must be one of %s" % (key, sorted(allowed)))
    return value


def int_min(value, key, minimum, range_error=False):
    v = as_int(value, key)
    if v < minimum:
        if range_error:
            raise_err(ERR_VALIDATION_RANGE, "%s must be >= %s" % (key, minimum))
        raise_err(ERR_INVALID_REQUEST, "%s must be >= %s" % (key, minimum))
    return v
