"""Request body parsing / shape validation (ladder tiers 4 and 5)."""
from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import fail
from util import D, parse_dt, round_half_up

MISSING = object()


def body():
    """The request body as a dict.  Absent body is treated as ``{}``."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "request body must be valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


def present(data, key):
    return key in data and data[key] is not None


# ------------------------------------------------------------------ tier 4 --

def catalog_ref(data, key, tablename, required=True):
    """Resolve a body foreign key BEFORE shape validation (ladder tier 4).

    A key that is absent is left for shape validation to report as missing; a
    key carrying a non-string is left for shape validation to reject; a string
    that resolves to nothing is ERR_CATALOG_REF_NOT_FOUND.
    """
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if not isinstance(value, str):
        return None
    row = db.get(tablename, value)
    if row is None:
        fail("ERR_CATALOG_REF_NOT_FOUND", "%s %s does not exist" % (key, value))
    return row


# ------------------------------------------------------------------ tier 5 --

def _bad(key, detail):
    fail("ERR_INVALID_REQUEST", "%s %s" % (key, detail))


def string(data, key, required=True, default=None, max_length=None,
           allow_blank=False):
    if key not in data or data[key] is None:
        if required:
            _bad(key, "is required")
        return default
    value = data[key]
    if not isinstance(value, str):
        _bad(key, "must be a string")
    if not allow_blank and not value.strip():
        _bad(key, "must be a non-empty string")
    if max_length is not None and len(value) > max_length:
        _bad(key, "must be at most %d characters" % max_length)
    return value


def enum(data, key, choices, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            _bad(key, "is required")
        return default
    value = data[key]
    if not isinstance(value, str) or value not in choices:
        _bad(key, "must be one of %s" % ", ".join(choices))
    return value


def boolean(data, key, required=False, default=None):
    if key not in data or data[key] is None:
        if required:
            _bad(key, "is required")
        return default
    value = data[key]
    if not isinstance(value, bool):
        _bad(key, "must be a boolean")
    return value


def _numeric(data, key, required, default):
    if key not in data or data[key] is None:
        if required:
            _bad(key, "is required")
        return MISSING if default is MISSING else default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        _bad(key, "must be a number")
    try:
        return D(value)
    except (InvalidOperation, ValueError):
        _bad(key, "must be a number")


def number(data, key, required=True, default=None, minimum=None,
           exclusive_minimum=None, maximum=None, exclusive_maximum=None,
           places=None):
    value = _numeric(data, key, required, default)
    if value is None or value is MISSING:
        return None if value is MISSING else value
    value = D(value)
    if minimum is not None and value < D(minimum):
        _bad(key, "must be >= %s" % minimum)
    if exclusive_minimum is not None and value <= D(exclusive_minimum):
        _bad(key, "must be > %s" % exclusive_minimum)
    if maximum is not None and value > D(maximum):
        _bad(key, "must be <= %s" % maximum)
    if exclusive_maximum is not None and value >= D(exclusive_maximum):
        _bad(key, "must be < %s" % exclusive_maximum)
    if places is not None:
        value = round_half_up(value, places)
    return value


def integer(data, key, required=True, default=None, minimum=None,
            exclusive_minimum=None, maximum=None):
    if key not in data or data[key] is None:
        if required:
            _bad(key, "is required")
        return default
    value = data[key]
    if isinstance(value, bool):
        _bad(key, "must be an integer")
    if isinstance(value, float):
        if value != int(value):
            _bad(key, "must be an integer")
        value = int(value)
    if not isinstance(value, int):
        _bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(key, "must be >= %s" % minimum)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        _bad(key, "must be > %s" % exclusive_minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be <= %s" % maximum)
    return value


def instant(data, key, required=True, default=None):
    if key not in data or data[key] is None:
        if required:
            _bad(key, "is required")
        return default
    value = data[key]
    if not isinstance(value, str):
        _bad(key, "must be an ISO 8601 timestamp string")
    parsed = parse_dt(value)
    if parsed is None:
        _bad(key, "must be a valid ISO 8601 timestamp")
    return parsed


def array(data, key, required=True, min_length=None):
    if key not in data or data[key] is None:
        if required:
            _bad(key, "is required")
        return None
    value = data[key]
    if not isinstance(value, list):
        _bad(key, "must be an array")
    if min_length is not None and len(value) < min_length:
        _bad(key, "must contain at least %d item(s)" % min_length)
    return value


def enum_filter(name, choices):
    """Query-string filter whose value must belong to an enum."""
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in choices:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, ", ".join(choices)))
    return value


def string_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
