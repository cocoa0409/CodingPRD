"""Request body shape validation (ladder rung 7 -> ERR_INVALID_REQUEST)."""
from flask import request

from db import parse_dt
from errors import fail

MISSING = object()


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def present(data, key):
    return key in data and data[key] is not None


def req_str(data, key):
    value = data.get(key)
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string." % key)
    return value


def opt_str(data, key, default=None):
    if not present(data, key):
        return default
    return req_str(data, key)


def req_text(data, key):
    """Required string that may not be blank but keeps surrounding text as-is."""
    return req_str(data, key)


def req_enum(data, key, allowed):
    value = data.get(key)
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, key, allowed, default=None):
    if not present(data, key):
        return default
    return req_enum(data, key, allowed)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(data, key, minimum=None, exclusive_minimum=None):
    value = data.get(key)
    if not _is_int(value):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % key)
    _check_int_bounds(key, value, minimum, exclusive_minimum)
    return value


def opt_int(data, key, default=None, minimum=None, exclusive_minimum=None):
    if not present(data, key):
        return default
    return req_int(data, key, minimum, exclusive_minimum)


def _check_int_bounds(key, value, minimum, exclusive_minimum):
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (key, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        fail("ERR_INVALID_REQUEST", "%s must be greater than %s." % (key, exclusive_minimum))


def req_number(data, key, minimum=None, maximum=None):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s may not exceed %s." % (key, maximum))
    return value


def opt_bool(data, key, default=None):
    if not present(data, key):
        return default
    value = data.get(key)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % key)
    return value


def req_dt(data, key):
    value = data.get(key)
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp string." % key)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 timestamp." % key)
    return value, parsed


def req_object(data, key):
    value = data.get(key)
    if not isinstance(value, dict):
        fail("ERR_INVALID_REQUEST", "%s must be an object." % key)
    for tag_key, tag_value in value.items():
        if not isinstance(tag_key, str) or not isinstance(tag_value, str):
            fail("ERR_INVALID_REQUEST", "%s must map string keys to string values." % key)
    return dict(value)


def req_str_list(data, key):
    value = data.get(key)
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array." % key)
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            fail("ERR_INVALID_REQUEST", "%s must contain non-empty strings." % key)
    return list(value)


def req_interval(data, start_key, end_key):
    start_raw, start = req_dt(data, start_key)
    end_raw, end = req_dt(data, end_key)
    if not end > start:
        fail("ERR_INVALID_REQUEST", "%s must be strictly after %s." % (end_key, start_key))
    return (start_raw, start), (end_raw, end)
