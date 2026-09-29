"""Body well-formedness helpers — ladder rung 16 (ERR_INVALID_REQUEST, HTTP 400)."""

from flask import request

import clock
from errors import fail

E = "ERR_INVALID_REQUEST"


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail(E, "request body must be a JSON object")
    if not isinstance(payload, dict):
        fail(E, "request body must be a JSON object")
    return payload


def present(data, name):
    return name in data and data.get(name) is not None


def req_str(data, name, min_len=1, max_len=None):
    if not present(data, name):
        fail(E, "%s is required" % name)
    value = data.get(name)
    if not isinstance(value, str):
        fail(E, "%s must be a string" % name)
    if len(value) < min_len:
        fail(E, "%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail(E, "%s must be at most %d characters" % (name, max_len))
    return value


def opt_str(data, name, default=None, max_len=None):
    if not present(data, name):
        return default
    value = data.get(name)
    if not isinstance(value, str):
        fail(E, "%s must be a string" % name)
    if max_len is not None and len(value) > max_len:
        fail(E, "%s must be at most %d characters" % (name, max_len))
    return value


def _as_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        fail(E, "%s must be an integer" % name)
    return value


def req_int(data, name, minimum=0, maximum=None):
    if not present(data, name):
        fail(E, "%s is required" % name)
    value = _as_int(name, data.get(name))
    if minimum is not None and value < minimum:
        fail(E, "%s must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail(E, "%s must be at most %s" % (name, maximum))
    return value


def opt_int(data, name, default=0, minimum=0, maximum=None):
    if not present(data, name):
        return default
    value = _as_int(name, data.get(name))
    if minimum is not None and value < minimum:
        fail(E, "%s must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail(E, "%s must be at most %s" % (name, maximum))
    return value


def req_number(data, name, minimum=None, maximum=None):
    if not present(data, name):
        fail(E, "%s is required" % name)
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(E, "%s must be a number" % name)
    if minimum is not None and value < minimum:
        fail(E, "%s must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail(E, "%s must be at most %s" % (name, maximum))
    return value


def req_bool(data, name):
    if not present(data, name):
        fail(E, "%s is required" % name)
    value = data.get(name)
    if not isinstance(value, bool):
        fail(E, "%s must be a boolean" % name)
    return value


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        fail(E, "%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, name, allowed, default=None):
    if not present(data, name):
        return default
    value = data.get(name)
    if not isinstance(value, str) or value not in allowed:
        fail(E, "%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def req_date(data, name):
    if not present(data, name):
        fail(E, "%s is required" % name)
    return clock.parse_date(data.get(name), E)


def opt_date(data, name, default=None):
    if not present(data, name):
        return default
    return clock.parse_date(data.get(name), E)


def req_id(data, name):
    """A foreign-key body field: must be a non-empty string when supplied."""
    if not present(data, name):
        fail(E, "%s is required" % name)
    value = data.get(name)
    if not isinstance(value, str) or not value:
        fail(E, "%s must be a string identifier" % name)
    return value


def raw_id(data, name):
    """Return an FK candidate without validating it (used before existence rungs)."""
    value = data.get(name)
    if isinstance(value, str) and value:
        return value
    return None
