"""Ladder rung 3: request shape validation (PRD 2.6).

Every failure here raises ERR_INVALID_REQUEST (HTTP 400).
"""
from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import ApiError


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Return the JSON body as a dict; an absent body reads as {}."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or not raw.strip():
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        _bad("Request body is not valid JSON.")
    if not isinstance(payload, dict):
        _bad("Request body must be a JSON object.")
    return payload


def present(data, field):
    return field in data and data[field] is not None


def req_string(data, field):
    if not present(data, field):
        _bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        _bad("Field '%s' must be a non-empty string." % field)
    return value


def opt_string(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % field)
    return value


def req_id(data, field):
    """A foreign-key style identifier: a non-empty string."""
    return req_string(data, field)


def opt_id(data, field):
    if not present(data, field):
        return None
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        _bad("Field '%s' must be a non-empty string." % field)
    return value


def req_int(data, field, minimum=None, maximum=None):
    if not present(data, field):
        _bad("Field '%s' is required." % field)
    return _as_int(data[field], field, minimum, maximum)


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if not present(data, field):
        return default
    return _as_int(data[field], field, minimum, maximum)


def _as_int(value, field, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be <= %s." % (field, maximum))
    return value


def req_number(data, field, minimum=None, exclusive_minimum=None):
    if not present(data, field):
        _bad("Field '%s' is required." % field)
    return _as_number(data[field], field, minimum, exclusive_minimum)


def opt_number(data, field, default=None, minimum=None, exclusive_minimum=None):
    if not present(data, field):
        return default
    return _as_number(data[field], field, minimum, exclusive_minimum)


def _as_number(value, field, minimum, exclusive_minimum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' must be a number." % field)
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        _bad("Field '%s' must be a number." % field)
    if not number.is_finite():
        _bad("Field '%s' must be a finite number." % field)
    if minimum is not None and number < Decimal(str(minimum)):
        _bad("Field '%s' must be >= %s." % (field, minimum))
    if exclusive_minimum is not None and number <= Decimal(str(exclusive_minimum)):
        _bad("Field '%s' must be > %s." % (field, exclusive_minimum))
    return number


def req_bool(data, field):
    if not present(data, field):
        _bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % field)
    return value


def opt_bool(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % field)
    return value


def req_enum(data, field, allowed):
    value = req_string(data, field)
    if value not in allowed:
        _bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        _bad("Field '%s' must be one of %s." % (field, ", ".join(allowed)))
    return value


def req_datetime(data, field):
    if not present(data, field):
        _bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, str):
        _bad("Field '%s' must be an ISO 8601 timestamp." % field)
    parsed = clock.parse(value)
    if parsed is None:
        _bad("Field '%s' must be an ISO 8601 timestamp." % field)
    return parsed


def req_string_list(data, field, allowed=None):
    if not present(data, field):
        _bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, list) or len(value) == 0:
        _bad("Field '%s' must be a non-empty array." % field)
    for member in value:
        if not isinstance(member, str):
            _bad("Field '%s' members must be strings." % field)
        if allowed is not None and member not in allowed:
            _bad("Field '%s' members must be drawn from %s." % (field, ", ".join(allowed)))
    return list(value)


# --- query parameters ------------------------------------------------------

KNOWN_PAGINATION = ("limit", "offset")


def query_string(args, name):
    if name not in args:
        return None
    value = args.get(name)
    if value is None or not str(value).strip():
        _bad("Query parameter '%s' must be a non-empty string." % name)
    return value


def query_enum(args, name, allowed):
    value = query_string(args, name)
    if value is None:
        return None
    if value not in allowed:
        _bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value
