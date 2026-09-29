"""Request-shape validation — ladder rung 3, always ERR_INVALID_REQUEST (400)."""

from flask import request

from common import parse_day, parse_instant
from errors import fail

_MISSING = object()


def body():
    """Parse the JSON body. An absent body is treated as an empty object."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return parsed


def _present(data, name, required):
    if name not in data or data[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return False
    return True


def string_field(data, name, required=True, default=None):
    if not _present(data, name, required):
        return default
    value = data[name]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string." % name)
    return value


def enum_field(data, name, members, required=True, default=None):
    if not _present(data, name, required):
        return default
    value = data[name]
    if not isinstance(value, str) or value not in members:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(members)))
    return value


def int_field(data, name, required=True, default=None, minimum=None, choices=None):
    if not _present(data, name, required):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if choices is not None and value not in choices:
        fail("ERR_INVALID_REQUEST",
             "%s must be one of %s." % (name, ", ".join(str(c) for c in choices)))
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (name, minimum))
    return value


def number_field(data, name, required=True, default=None, minimum=None, exclusive_minimum=None):
    if not _present(data, name, required):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (name, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        fail("ERR_INVALID_REQUEST",
             "%s must be greater than %s." % (name, exclusive_minimum))
    return value


def bool_field(data, name, required=True, default=None):
    if not _present(data, name, required):
        return default
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)
    return value


def day_field(data, name, required=True, default=None):
    """A calendar date input; the raw string is returned so it can be echoed."""
    if not _present(data, name, required):
        return default
    value = data[name]
    if not isinstance(value, str) or parse_day(value) is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 date." % name)
    return value


def instant_field(data, name, required=True, default=None):
    if not _present(data, name, required):
        return default
    value = data[name]
    if not isinstance(value, str) or parse_instant(value) is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp." % name)
    return value
