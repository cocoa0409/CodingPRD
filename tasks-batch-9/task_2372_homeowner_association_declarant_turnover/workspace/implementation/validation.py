"""Request-shape validation (ladder step 6 — ERR_INVALID_REQUEST 400).

Computed and system-owned fields a client supplies anyway are silently ignored.
"""
import re

from flask import request

import util
from errors import ApiError

_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")

_MISSING = object()


def _invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise _invalid("Request body must be a JSON object.")
    return payload


def get_str(data, field, required=True, min_len=1, max_len=None, default=None):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise _invalid("%s is required." % field)
        return default
    if not isinstance(value, str):
        raise _invalid("%s must be a string." % field)
    if min_len is not None and len(value.strip()) < min_len:
        raise _invalid("%s must be at least %d characters." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        raise _invalid("%s must be at most %d characters." % (field, max_len))
    return value


def get_int(data, field, required=True, minimum=None, maximum=None, default=None):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise _invalid("%s is required." % field)
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid("%s must be an integer." % field)
    if minimum is not None and value < minimum:
        raise _invalid("%s must be >= %d." % (field, minimum))
    if maximum is not None and value > maximum:
        raise _invalid("%s must be <= %d." % (field, maximum))
    return value


def get_number(data, field, required=True, minimum=None, maximum=None, default=None):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise _invalid("%s is required." % field)
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid("%s must be a number." % field)
    decimal_value = util.to_decimal(value)
    if minimum is not None and decimal_value < util.to_decimal(minimum):
        raise _invalid("%s must be >= %s." % (field, minimum))
    if maximum is not None and decimal_value > util.to_decimal(maximum):
        raise _invalid("%s must be <= %s." % (field, maximum))
    return decimal_value


def get_bool(data, field, required=True, default=None):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise _invalid("%s is required." % field)
        return default
    if not isinstance(value, bool):
        raise _invalid("%s must be a boolean." % field)
    return value


def get_enum(data, field, allowed, required=True, default=None):
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise _invalid("%s is required." % field)
        return default
    if not isinstance(value, str) or value not in allowed:
        raise _invalid("%s must be one of %s." % (field, ", ".join(allowed)))
    return value


def get_datetime(data, field, required=True, default=None):
    """Validates an ISO 8601 instant and returns (raw_string, datetime)."""
    value = data.get(field, _MISSING)
    if value is _MISSING or value is None:
        if required:
            raise _invalid("%s is required." % field)
        return default, None
    if not isinstance(value, str):
        raise _invalid("%s must be an ISO 8601 timestamp string." % field)
    parsed = util.parse_dt(value)
    if parsed is None:
        raise _invalid("%s must be a valid ISO 8601 timestamp." % field)
    return value, parsed


def get_period_month(data, field, required=True):
    value = get_str(data, field, required=required)
    if value is None:
        return None
    if not _MONTH_RE.match(value):
        raise _invalid("%s must match YYYY-MM with a month between 01 and 12." % field)
    return value


def get_fk(data, field):
    """Return a foreign key candidate for existence resolution, or None when the
    field is absent/ill-typed (the shape check then reports it)."""
    value = data.get(field)
    if isinstance(value, str) and value:
        return value
    return None


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name):
    value = query_filter(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    return None


def query_int(name):
    value = query_filter(name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
