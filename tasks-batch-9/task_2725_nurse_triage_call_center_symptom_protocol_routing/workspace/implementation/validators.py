"""Request-body helpers. Every failure here is validation priority 3,
ERR_INVALID_REQUEST (HTTP 400): a missing required field, an enum value outside
its declared set, a numeric value outside its declared range, an inverted
interval, or a malformed ISO-8601 instant.
"""
from flask import request

from errors import ApiError
from util import parse_date, parse_iso, HHMM_RE

_MISSING = object()


def bad(detail):
    raise ApiError("ERR_INVALID_REQUEST", detail)


def body():
    """Parse the JSON body. An absent body behaves like an empty object so the
    'required field missing' branch produces the error rather than a 500."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body must be valid JSON.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def present(data, name):
    value = data.get(name, _MISSING)
    return value is not _MISSING and value is not None


def _fetch(data, name, required):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        if required:
            bad("%s is required." % name)
        return None
    return value


def get_string(data, name, required=True, min_len=1, max_len=None, pattern=None,
               allow_empty=False):
    value = _fetch(data, name, required)
    if value is None:
        return None
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if not allow_empty and len(value) < min_len:
        bad("%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s may be at most %d characters." % (name, max_len))
    if pattern is not None and not pattern.match(value):
        bad("%s is malformed." % name)
    return value


def get_enum(data, name, allowed, required=True):
    value = _fetch(data, name, required)
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def get_int(data, name, required=True, minimum=None, maximum=None):
    value = _fetch(data, name, required)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("%s may not be below %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s may not exceed %s." % (name, maximum))
    return value


def get_number(data, name, required=True):
    """A decimal-degrees style number; range checks are the caller's business
    because latitude/longitude bounds are ERR_INVALID_LOCATION, not 400."""
    value = _fetch(data, name, required)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number." % name)
    return float(value)


def get_bool(data, name, required=True, default=None):
    value = _fetch(data, name, required)
    if value is None:
        return default
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def get_timestamp(data, name, required=True):
    value = _fetch(data, name, required)
    if value is None:
        return None
    if not isinstance(value, str):
        bad("%s must be an ISO-8601 UTC timestamp." % name)
    parsed = parse_iso(value)
    if parsed is None:
        bad("%s must be an ISO-8601 UTC timestamp." % name)
    return parsed


def get_date(data, name, required=True):
    value = _fetch(data, name, required)
    if value is None:
        return None
    if not isinstance(value, str):
        bad("%s must be a YYYY-MM-DD calendar date." % name)
    parsed = parse_date(value)
    if parsed is None:
        bad("%s must be a YYYY-MM-DD calendar date." % name)
    return parsed


def get_hhmm(data, name, required=True):
    value = _fetch(data, name, required)
    if value is None:
        return None
    if not isinstance(value, str) or not HHMM_RE.match(value):
        bad("%s must be a UTC HH:MM value." % name)
    return value


def query_enum(name, allowed):
    """Query-string filters are never a 404; an unknown value simply matches
    nothing, but a value outside the declared enum set is still malformed."""
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return raw


def query_string(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_timestamp(name, required=False):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            bad("%s is required." % name)
        return None
    parsed = parse_iso(raw)
    if parsed is None:
        bad("%s must be an ISO-8601 UTC timestamp." % name)
    return parsed
