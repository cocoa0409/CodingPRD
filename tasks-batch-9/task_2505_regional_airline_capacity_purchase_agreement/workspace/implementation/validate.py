"""Structural request validation (PRD 2.6, rejection precedence 5)."""

from flask import request

from core import (dec, decimal_places, is_month, parse_date, parse_iso_datetime,
                  round2, round3)
from errors import fail

_MISSING = object()


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return payload


def _raw(data, name, required):
    if name not in data or data[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required" % name)
        return _MISSING
    return data[name]


def present(data, name):
    return name in data and data[name] is not None


def string_field(data, name, required=True):
    value = _raw(data, name, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string" % name)
    return value


def enum_field(data, name, allowed, required=True):
    value = _raw(data, name, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "%s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def _numeric(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number" % name)
    try:
        return dec(value)
    except Exception:
        fail("ERR_INVALID_REQUEST", "%s must be a number" % name)


def money_field(data, name, required=True, allow_zero=False):
    """Monetary input: 2 decimal places maximum, strictly positive unless allow_zero."""
    value = _raw(data, name, required)
    if value is _MISSING:
        return None
    amount = _numeric(value, name)
    if decimal_places(amount) > 2:
        fail("ERR_INVALID_REQUEST", "%s may not carry more than two decimals" % name)
    if allow_zero:
        if amount < 0:
            fail("ERR_INVALID_REQUEST", "%s must be at least 0" % name)
    elif amount <= 0:
        fail("ERR_INVALID_REQUEST", "%s must be strictly greater than zero" % name)
    return round2(amount)


def hours_field(data, name, required=True):
    """Block hours: 3 decimal places maximum, strictly positive."""
    value = _raw(data, name, required)
    if value is _MISSING:
        return None
    amount = _numeric(value, name)
    if decimal_places(amount) > 3:
        fail("ERR_INVALID_REQUEST", "%s may not carry more than three decimals" % name)
    if amount <= 0:
        fail("ERR_INVALID_REQUEST", "%s must be strictly greater than zero" % name)
    return round3(amount)


def int_field(data, name, required=True, minimum=None):
    value = _raw(data, name, required)
    if value is _MISSING:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d" % (name, minimum))
    return value


def datetime_field(data, name, required=True):
    """Returns (raw_string, aware_datetime)."""
    value = _raw(data, name, required)
    if value is _MISSING:
        return None, None
    parsed = parse_iso_datetime(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant" % name)
    return value, parsed


def date_field(data, name, required=True):
    """Returns (raw_string, date). Calendar date in YYYY-MM-DD form."""
    value = _raw(data, name, required)
    if value is _MISSING:
        return None, None
    parsed = parse_date(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD calendar date" % name)
    return value, parsed


def month_field(data, name, required=True):
    value = _raw(data, name, required)
    if value is _MISSING:
        return None
    if not is_month(value):
        fail("ERR_INVALID_REQUEST", "%s must be a YYYY-MM month" % name)
    return value


# NOTE: station_code is described in PRD 3.2 as a three-letter code, but neither
# the PRD's ERR_INVALID_REQUEST enumeration (2.12 item 5) nor the error catalogue
# lists a length constraint, so no length check is enforced here.
