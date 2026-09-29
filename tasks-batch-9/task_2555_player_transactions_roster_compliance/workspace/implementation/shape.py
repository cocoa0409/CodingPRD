"""Request-shape validation (validation ladder rule 7 -> ERR_INVALID_REQUEST)."""
from flask import request

from errors import fail
from store import parse_dt

MISSING = object()


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


def present(data, key):
    return key in data and data[key] is not None


def raw(data, key):
    return data.get(key)


def req_str(data, key, min_len=1, max_len=None):
    value = data.get(key)
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s is required" % key)
    text = value.strip()
    if len(text) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must not be blank" % key)
    if max_len is not None and len(text) > max_len:
        fail("ERR_INVALID_REQUEST", "%s exceeds maximum length" % key)
    return text


def opt_str(data, key, default=None, min_len=1, max_len=None):
    if not present(data, key):
        return default
    return req_str(data, key, min_len=min_len, max_len=max_len)


def req_enum(data, key, allowed):
    value = data.get(key)
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if not present(data, key):
        return default
    return req_enum(data, key, allowed)


def req_int(data, key, minimum=None, maximum=None):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s below minimum" % key)
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s above maximum" % key)
    return value


def opt_int(data, key, default=None, minimum=None, maximum=None):
    if not present(data, key):
        return default
    return req_int(data, key, minimum=minimum, maximum=maximum)


def req_bool(data, key):
    value = data.get(key)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % key)
    return value


def opt_bool(data, key, default=False):
    if not present(data, key):
        return default
    return req_bool(data, key)


def req_dt(data, key):
    value = data.get(key)
    parsed = parse_dt(value) if isinstance(value, str) else None
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant" % key)
    return parsed


def opt_dt(data, key, default=None):
    if not present(data, key):
        return default
    return req_dt(data, key)


def req_ref(data, key):
    """A required foreign-key reference: a non-blank identifier string."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "%s is required" % key)
    return value.strip()


def opt_ref(data, key, default=None):
    if not present(data, key):
        return default
    return req_ref(data, key)
