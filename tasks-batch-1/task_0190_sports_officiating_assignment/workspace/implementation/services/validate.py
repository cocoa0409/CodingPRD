"""Input-validity helpers (ERR_INVALID_REQUEST, priority 17 / PRD §2.9 last gate).

These are structural input checks: required fields present, enums recognized,
numeric ranges respected. They are invoked AFTER auth/existence/state/ownership
and business constraints per the PRD ordering, except where a create endpoint
has no prior gates (then input validity is effectively the first failing gate).
"""
from flask import request

from errors import err, ERR_INVALID_REQUEST


def body():
    """Parse JSON body; tolerate empty body as {}."""
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def require(data, *names):
    for n in names:
        if n not in data or data[n] is None:
            err(ERR_INVALID_REQUEST, "missing required field: %s" % n)


def require_str(data, name):
    require(data, name)
    v = data[name]
    if not isinstance(v, str) or not v.strip():
        err(ERR_INVALID_REQUEST, "%s must be a non-empty string" % name)
    return v


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, str):
        err(ERR_INVALID_REQUEST, "%s must be a string" % name)
    return v


def enum(data, name, allowed, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            err(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    v = data[name]
    if v not in allowed:
        err(ERR_INVALID_REQUEST, "%s must be one of %s" % (name, sorted(allowed)))
    return v


def integer(data, name, required=True, default=None, minimum=None):
    if name not in data or data[name] is None:
        if required:
            err(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        err(ERR_INVALID_REQUEST, "%s must be an integer" % name)
    if minimum is not None and v < minimum:
        err(ERR_INVALID_REQUEST, "%s must be >= %s" % (name, minimum))
    return v


def number(data, name, required=True, default=None, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        if required:
            err(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err(ERR_INVALID_REQUEST, "%s must be a number" % name)
    if minimum is not None and v < minimum:
        err(ERR_INVALID_REQUEST, "%s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        err(ERR_INVALID_REQUEST, "%s must be <= %s" % (name, maximum))
    return float(v)


def boolean(data, name, required=False, default=None):
    if name not in data or data[name] is None:
        if required:
            err(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    v = data[name]
    if not isinstance(v, bool):
        err(ERR_INVALID_REQUEST, "%s must be a boolean" % name)
    return v
