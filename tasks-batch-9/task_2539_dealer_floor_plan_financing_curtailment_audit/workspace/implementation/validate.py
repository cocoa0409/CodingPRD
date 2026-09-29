"""Band 5 payload validation: shapes, enumerations and ranges (400)."""

from flask import request

import db
from errors import ApiError

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, min_len=1, max_len=None):
    if name not in data or data[name] is None:
        bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if len(value) < min_len:
        bad("%s is too short." % name)
    if max_len is not None and len(value) > max_len:
        bad("%s is too long." % name)
    return value


def opt_str(data, name, min_len=1, max_len=None, default=None):
    if name not in data or data[name] is None:
        return default
    return req_str(data, name, min_len=min_len, max_len=max_len)


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    return req_enum(data, name, allowed)


def _as_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % name)
    return value


def req_int(data, name, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        bad("%s is required." % name)
    value = _as_int(name, data[name])
    if minimum is not None and value < minimum:
        bad("%s is below its minimum." % name)
    if maximum is not None and value > maximum:
        bad("%s is above its maximum." % name)
    return value


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if name not in data or data[name] is None:
        return default
    return req_int(data, name, minimum=minimum, maximum=maximum)


def req_bool(data, name):
    if name not in data or data[name] is None:
        bad("%s is required." % name)
    value = data[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def req_instant(data, name):
    value = req_str(data, name)
    try:
        return db.parse_instant(value)
    except ValueError:
        bad("%s must be an ISO 8601 instant." % name)


def opt_instant(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_instant(data, name)


def req_ref(data, name):
    """A required identifier reference: must be a non-empty string."""
    return req_str(data, name)


def opt_ref(data, name):
    if name not in data or data[name] is None:
        return None
    return req_str(data, name)


def upper_alnum(value):
    return all(("A" <= ch <= "Z") or ("0" <= ch <= "9") for ch in value)
