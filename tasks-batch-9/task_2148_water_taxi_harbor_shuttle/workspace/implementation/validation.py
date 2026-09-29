"""Payload validity helpers — rung 6 of the rejection ladder (ERR_INVALID_REQUEST)."""

from flask import request

from errors import ApiError
from store import parse_date, parse_instant

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Request body as a JSON object; anything else is a malformed request."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    payload = request.get_json(silent=True, force=True)
    if payload is None or not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def raw_value(payload, key):
    return payload.get(key, _MISSING)


def is_missing(value):
    return value is _MISSING


def get_string(payload, key, required=True, default=None,
               min_len=None, max_len=None, nullable=False):
    value = payload.get(key, _MISSING)
    if value is _MISSING:
        if required:
            bad("%s is required." % key)
        return default
    if value is None:
        if nullable or not required:
            return None
        bad("%s may not be null." % key)
    if not isinstance(value, str):
        bad("%s must be a string." % key)
    if min_len is not None and len(value) < min_len:
        bad("%s must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (key, max_len))
    return value


def get_integer(payload, key, required=True, default=None,
                minimum=None, maximum=None, nullable=False):
    value = payload.get(key, _MISSING)
    if value is _MISSING:
        if required:
            bad("%s is required." % key)
        return default
    if value is None:
        if nullable or not required:
            return None
        bad("%s may not be null." % key)
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("%s must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %s." % (key, maximum))
    return value


def get_number(payload, key, required=True, default=None,
               minimum=None, exclusive_minimum=None):
    value = payload.get(key, _MISSING)
    if value is _MISSING:
        if required:
            bad("%s is required." % key)
        return default
    if value is None:
        if not required:
            return default
        bad("%s may not be null." % key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number." % key)
    if minimum is not None and value < minimum:
        bad("%s must be at least %s." % (key, minimum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        bad("%s must be greater than %s." % (key, exclusive_minimum))
    return value


def get_boolean(payload, key, required=False, default=False):
    value = payload.get(key, _MISSING)
    if value is _MISSING:
        if required:
            bad("%s is required." % key)
        return default
    if value is None and not required:
        return default
    if not isinstance(value, bool):
        bad("%s must be a boolean." % key)
    return value


def get_enum(payload, key, allowed, required=True, default=None, nullable=False):
    value = payload.get(key, _MISSING)
    if value is _MISSING:
        if required:
            bad("%s is required." % key)
        return default
    if value is None:
        if nullable or not required:
            return None
        bad("%s may not be null." % key)
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def get_calendar_date(payload, key, required=True, default=None, nullable=False):
    """Returns (raw_string, date) or (None, None)."""
    value = payload.get(key, _MISSING)
    if value is _MISSING:
        if required:
            bad("%s is required." % key)
        return default, None
    if value is None:
        if nullable or not required:
            return None, None
        bad("%s may not be null." % key)
    parsed = parse_date(value)
    if parsed is None:
        bad("%s must be a calendar date in YYYY-MM-DD form." % key)
    return value, parsed


def get_utc_instant(payload, key, required=True):
    """Returns (raw_string, datetime)."""
    value = payload.get(key, _MISSING)
    if value is _MISSING:
        if required:
            bad("%s is required." % key)
        return None, None
    if value is None:
        if not required:
            return None, None
        bad("%s may not be null." % key)
    parsed = parse_instant(value)
    if parsed is None:
        bad("%s must be an ISO 8601 UTC instant." % key)
    return value, parsed


def get_string_list(payload, key, required=True):
    value = payload.get(key, _MISSING)
    if value is _MISSING:
        if required:
            bad("%s is required." % key)
        return []
    if not isinstance(value, list):
        bad("%s must be an array." % key)
    for item in value:
        if not isinstance(item, str) or item == "":
            bad("%s must contain only non-empty strings." % key)
    return value


def fk_candidate(payload, key, required=True):
    """Rung 4 pre-check: a foreign key can only be *resolved* when it is present
    and a string.  Anything else falls through to rung 6."""
    value = payload.get(key, _MISSING)
    if value is _MISSING or value is None or not isinstance(value, str) or value == "":
        return None
    return value
