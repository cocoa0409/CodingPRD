"""Rejection-ladder rung 5: request-shape validation (PRD 2.6 item 5)."""

from decimal import Decimal, InvalidOperation

from flask import request

from calc import dec, rhu
from errors import fail
from store import parse_iso

_MISSING = object()


def body():
    """The JSON body as a dict; a non-object body is a shape failure."""
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return raw


def raw_id(payload, key):
    """A foreign key value as supplied (used by the existence rung)."""
    return payload.get(key)


def _bad(key, detail):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (key, detail))


def req_string(payload, key, min_len=1, max_len=None):
    value = payload.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad(key, "is required")
    if not isinstance(value, str):
        _bad(key, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(key, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(key, "must be at most %d characters" % max_len)
    return value


def req_int(payload, key, minimum=None, maximum=None):
    value = payload.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad(key, "is required")
    return _as_int(key, value, minimum, maximum)


def opt_int(payload, key, minimum=None, maximum=None, default=None):
    value = payload.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    return _as_int(key, value, minimum, maximum)


def _as_int(key, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(key, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be at most %s" % maximum)
    return value


def req_number(payload, key, minimum=None, maximum=None, places=None):
    value = payload.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad(key, "is required")
    return _as_number(key, value, minimum, maximum, places)


def opt_number(payload, key, minimum=None, maximum=None, places=None, default=None):
    value = payload.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    return _as_number(key, value, minimum, maximum, places)


def _as_number(key, value, minimum, maximum, places):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _bad(key, "must be a number")
    try:
        number = dec(value)
    except (InvalidOperation, ValueError):
        _bad(key, "must be a number")
    if minimum is not None and number < dec(minimum):
        _bad(key, "must be at least %s" % minimum)
    if maximum is not None and number > dec(maximum):
        _bad(key, "must be at most %s" % maximum)
    if places is not None:
        number = rhu(number, places)
    return number


def req_enum(payload, key, allowed):
    value = payload.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad(key, "is required")
    if not isinstance(value, str) or value not in allowed:
        _bad(key, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(payload, key, allowed, default=None):
    value = payload.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        _bad(key, "must be one of %s" % ", ".join(allowed))
    return value


def req_bool(payload, key):
    value = payload.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad(key, "is required")
    if not isinstance(value, bool):
        _bad(key, "must be a boolean")
    return value


def req_datetime(payload, key):
    value = payload.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad(key, "is required")
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        _bad(key, "must be a valid ISO 8601 UTC datetime")


def opt_datetime(payload, key, default=None):
    value = payload.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        _bad(key, "must be a valid ISO 8601 UTC datetime")


def req_enum_list(payload, key, allowed, min_items=0, max_items=None):
    value = payload.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad(key, "is required")
    if not isinstance(value, list):
        _bad(key, "must be an array")
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            _bad(key, "may only contain %s" % ", ".join(allowed))
    if len(set(value)) != len(value):
        _bad(key, "must contain distinct codes")
    if min_items is not None and len(value) < min_items:
        _bad(key, "must contain at least %d codes" % min_items)
    if max_items is not None and len(value) > max_items:
        _bad(key, "must contain at most %d codes" % max_items)
    return list(value)


def query_enum(key, allowed, default=None):
    value = request.args.get(key)
    if value is None or value == "":
        return default
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def query_datetime(key, default=None):
    value = request.args.get(key)
    if value is None or value == "":
        return default
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be a valid ISO 8601 UTC datetime." % key)


def query_id(key):
    value = request.args.get(key)
    if value is None or value == "":
        return None
    return value
