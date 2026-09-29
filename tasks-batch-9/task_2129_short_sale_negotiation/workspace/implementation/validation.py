"""Ladder rung 7: request-shape validation (PRD §2.6 item 7).

Every failure here raises ERR_INVALID_REQUEST / 400.  Bounds that the PRD
assigns their own error code (the servicer commission cap, the lien balance
cap, ...) are deliberately NOT enforced here.
"""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from timeutil import parse_iso8601


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _missing(name):
    fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)


def req_string(data, name, allow_empty=False):
    if name not in data or data[name] is None:
        _missing(name)
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if not allow_empty and not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be non-empty." % name)
    return value


def opt_string(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    return value


def req_enum(data, name, allowed):
    value = req_string(data, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' has an unrecognised value." % name)
    return value


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    return req_enum(data, name, allowed)


def _as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    return value


def req_int(data, name, minimum=None, maximum=None):
    if name not in data or data[name] is None:
        _missing(name)
    value = _as_int(data[name], name)
    _bounds(value, name, minimum, maximum)
    return value


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if name not in data or data[name] is None:
        return default
    value = _as_int(data[name], name)
    _bounds(value, name, minimum, maximum)
    return value


def _bounds(value, name, minimum, maximum):
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, maximum))


def req_version(data, name):
    """Optimistic-concurrency field: a non-negative integer (or its digits)."""
    if name not in data or data[name] is None:
        _missing(name)
    value = data[name]
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)


def req_decimal(data, name, minimum=None, maximum=None, exclusive_min=False):
    """A decimal fraction supplied as a JSON number (or numeric string)."""
    if name not in data or data[name] is None:
        _missing(name)
    value = data[name]
    if isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    if isinstance(value, (int, float)):
        dec = Decimal(str(value))
    elif isinstance(value, str):
        try:
            dec = Decimal(value.strip())
        except (InvalidOperation, ValueError):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    else:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    if not dec.is_finite():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a finite number." % name)
    if minimum is not None:
        if exclusive_min and dec <= minimum:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be > %s." % (name, minimum))
        if not exclusive_min and dec < minimum:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and dec > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, maximum))
    return dec


def req_datetime(data, name):
    if name not in data or data[name] is None:
        _missing(name)
    parsed = parse_iso8601(data[name])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO-8601 instant." % name)
    return parsed


def opt_string_list(data, name, default=None):
    if name not in data or data[name] is None:
        return list(default or [])
    value = data[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an array of strings." % name)
    return list(value)
