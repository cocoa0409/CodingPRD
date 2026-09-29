"""Rank 7 request-shape validation. Every failure is ERR_INVALID_REQUEST (422)."""

import re

from flask import request

import clock
from errors import ApiError

MISSING = object()


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON request body as a dict. A missing body reads as an empty object."""
    try:
        payload = request.get_json(silent=True)
    except Exception:
        payload = None
    if payload is None:
        raw = request.get_data(cache=True, as_text=True)
        if raw is not None and raw.strip() not in ("", "null"):
            _bad("Request body must be a JSON object.")
        return {}
    if not isinstance(payload, dict):
        _bad("Request body must be a JSON object.")
    return payload


def present(payload, name):
    return name in payload and payload[name] is not None


def _get(payload, name, required):
    if name not in payload or payload[name] is None:
        if required:
            _bad("%s is required." % name)
        return MISSING
    return payload[name]


# --------------------------------------------------------------- primitives

def string(payload, name, required=True, min_len=1, max_len=None, pattern=None):
    value = _get(payload, name, required)
    if value is MISSING:
        return None
    if not isinstance(value, str):
        _bad("%s must be a string." % name)
    if min_len is not None and len(value) < min_len:
        _bad("%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("%s must be at most %d characters." % (name, max_len))
    if pattern is not None and not re.match(pattern, value):
        _bad("%s is malformed." % name)
    return value


def identifier(payload, name, required=True):
    """A body reference to another resource. Existence is checked later, at rank 8."""
    value = _get(payload, name, required)
    if value is MISSING:
        return None
    if not isinstance(value, str) or value.strip() == "":
        _bad("%s must be a non-empty string identifier." % name)
    return value


def integer(payload, name, required=True, minimum=None, maximum=None):
    value = _get(payload, name, required)
    if value is MISSING:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        _bad("%s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("%s must be at most %d." % (name, maximum))
    return value


def boolean(payload, name, required=True, default=None):
    value = _get(payload, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, bool):
        _bad("%s must be a boolean." % name)
    return value


def enum(payload, name, values, required=True, default=None):
    value = _get(payload, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, str) or value not in values:
        _bad("%s must be one of %s." % (name, ", ".join(values)))
    return value


def timestamp(payload, name, required=True):
    value = _get(payload, name, required)
    if value is MISSING:
        return None
    if not isinstance(value, str):
        _bad("%s must be an ISO 8601 UTC instant." % name)
    parsed = clock.parse(value)
    if parsed is None:
        _bad("%s must be an ISO 8601 UTC instant." % name)
    return parsed


def string_array(payload, name, required=True, default=None, allow_empty=True,
                 error_id="ERR_INVALID_REQUEST"):
    """A duplicate-free array of strings."""
    value = _get(payload, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, list):
        raise ApiError(error_id, "%s must be an array of strings." % name)
    for item in value:
        if not isinstance(item, str):
            raise ApiError(error_id, "%s must be an array of strings." % name)
    if len(set(value)) != len(value):
        raise ApiError(error_id, "%s must not contain duplicates." % name)
    if not allow_empty and not value:
        raise ApiError(error_id, "%s must not be empty." % name)
    return value


def cents_map(payload, name, required=False, default=None):
    """An object whose keys are fee codes and whose values are integers >= 0."""
    value = _get(payload, name, required)
    if value is MISSING:
        return {} if default is None else default
    if not isinstance(value, dict):
        _bad("%s must be an object." % name)
    for key, amount in value.items():
        if not isinstance(key, str) or key == "":
            _bad("%s keys must be fee codes." % name)
        if isinstance(amount, bool) or not isinstance(amount, int):
            _bad("%s values must be integers." % name)
        if amount < 0:
            _bad("%s values must be at least 0." % name)
    return dict(value)


def peek_body():
    """The body as a dict without raising — used by the rank 4/5 ownership checks,
    which are evaluated before request shape (PRD 2.6)."""
    try:
        payload = request.get_json(silent=True)
    except Exception:
        payload = None
    return payload if isinstance(payload, dict) else {}
