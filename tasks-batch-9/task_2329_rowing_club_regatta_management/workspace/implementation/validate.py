"""Payload-shape validation (ladder rung 5). Every failure is ERR_INVALID_REQUEST."""
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from util import parse_iso, round_half_up_1dp, to_decimal

MISSING = object()


def body():
    """Parse the JSON body. A malformed body is a shape failure."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    data = request.get_json(silent=True)
    if data is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _bad(name, why):
    fail("ERR_INVALID_REQUEST", "%s %s." % (name, why))


def present(data, name):
    return name in data


def string(data, name, required=True, default=None, nullable=False, allow_empty=False):
    if name not in data:
        if required:
            _bad(name, "is required")
        return default
    value = data[name]
    if value is None:
        if nullable or not required:
            return None
        _bad(name, "must be a string")
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not allow_empty and value.strip() == "":
        _bad(name, "must be a non-empty string")
    return value


def enum(data, name, allowed, required=True, default=None, nullable=False):
    if name not in data:
        if required:
            _bad(name, "is required")
        return default
    value = data[name]
    if value is None:
        if nullable or not required:
            return None
        _bad(name, "must be one of %s" % ", ".join(allowed))
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def integer(data, name, required=True, default=None, minimum=None, maximum=None,
            nullable=False):
    if name not in data:
        if required:
            _bad(name, "is required")
        return default
    value = data[name]
    if value is None:
        if nullable or not required:
            return None
        _bad(name, "must be an integer")
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %d" % maximum)
    return value


def number(data, name, required=True, default=None, nullable=False, one_dp=False):
    """Return a Decimal so that no float noise enters a comparison."""
    if name not in data:
        if required:
            _bad(name, "is required")
        return default
    value = data[name]
    if value is None:
        if nullable or not required:
            return None
        _bad(name, "must be a number")
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        _bad(name, "must be a number")
    try:
        dec = to_decimal(value)
    except (ValueError, ArithmeticError, InvalidOperation):
        _bad(name, "must be a number")
    if not dec.is_finite():
        _bad(name, "must be a finite number")
    if one_dp:
        dec = round_half_up_1dp(dec)
    return dec


def boolean(data, name, required=True, default=None, nullable=False):
    if name not in data:
        if required:
            _bad(name, "is required")
        return default
    value = data[name]
    if value is None:
        if nullable or not required:
            return None
        _bad(name, "must be a boolean")
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def datetime_field(data, name, required=True, nullable=False):
    """Return (parsed_datetime, raw_string) so the wire value can be echoed back."""
    if name not in data:
        if required:
            _bad(name, "is required")
        return None, None
    value = data[name]
    if value is None:
        if nullable or not required:
            return None, None
        _bad(name, "must be an ISO 8601 UTC datetime")
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 UTC datetime")
    try:
        parsed = parse_iso(value)
    except (ValueError, TypeError):
        _bad(name, "must be an ISO 8601 UTC datetime")
    return parsed, value


def id_array(data, name, required=False, default=None):
    if name not in data:
        if required:
            _bad(name, "is required")
        return list(default) if default is not None else []
    value = data[name]
    if value is None:
        if required:
            _bad(name, "must be an array of ids")
        return list(default) if default is not None else []
    if not isinstance(value, list):
        _bad(name, "must be an array of ids")
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            _bad(name, "must be an array of non-empty id strings")
    return list(value)


def enum_array(data, name, allowed, required=False, default=None):
    if name not in data:
        if required:
            _bad(name, "is required")
        return list(default) if default is not None else []
    value = data[name]
    if value is None:
        if required:
            _bad(name, "must be an array")
        return list(default) if default is not None else []
    if not isinstance(value, list):
        _bad(name, "must be an array")
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            _bad(name, "entries must be drawn from %s" % ", ".join(allowed))
    return list(value)


def object_array(data, name, required=True):
    if name not in data:
        if required:
            _bad(name, "is required")
        return []
    value = data[name]
    if not isinstance(value, list):
        _bad(name, "must be an array of objects")
    for item in value:
        if not isinstance(item, dict):
            _bad(name, "must be an array of objects")
    return value
