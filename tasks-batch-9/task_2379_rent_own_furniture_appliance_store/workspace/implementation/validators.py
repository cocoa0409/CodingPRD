"""Body shape validation — check 6 of the ordered sequence (PRD 2.9)."""

import json

from flask import request

import clock
from errors import ApiError

_MISSING = object()


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        _bad("The request body is not valid JSON.")
    if not isinstance(data, dict):
        _bad("The request body must be a JSON object.")
    return data


def _get(body, name, required):
    if name not in body or body[name] is None:
        if required:
            _bad("Field '%s' is required." % name)
        return _MISSING
    return body[name]


def string(body, name, required=True, default="", min_len=1, max_len=None):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % name)
    if len(value) < min_len:
        _bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("Field '%s' may not exceed %d characters." % (name, max_len))
    return value


def state_code(body, name, required=True, default=""):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % name)
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        _bad("Field '%s' must be a two-letter uppercase state code." % name)
    return value


def integer(body, name, required=True, default=0, minimum=None, maximum=None):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        _bad("Field '%s' may not be below %d." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' may not exceed %d." % (name, maximum))
    return value


def raw_integer(body, name, required=True, default=0):
    """An integer whose range is enforced by a later, dedicated check."""
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % name)
    return value


def number(body, name, required=True, default=0, minimum=None, maximum=None,
           exclusive_minimum=None):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' must be a number." % name)
    if minimum is not None and value < minimum:
        _bad("Field '%s' may not be below %s." % (name, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        _bad("Field '%s' must be greater than %s." % (name, exclusive_minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' may not exceed %s." % (name, maximum))
    return value


def boolean(body, name, required=True, default=False):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % name)
    return value


def enum(body, name, allowed, required=True, default=None):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        _bad("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def identifier(body, name, required=True, default=None):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value == "":
        _bad("Field '%s' must be a non-empty string identifier." % name)
    return value


def datetime_field(body, name, required=True, default=None):
    value = _get(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        _bad("Field '%s' must be an ISO 8601 timestamp string." % name)
    parsed = clock.parse(value)
    if parsed is None:
        _bad("Field '%s' must be an ISO 8601 timestamp string." % name)
    return parsed
