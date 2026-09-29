"""Request-shape validation (ladder gate 3, ERR_INVALID_REQUEST / 400).

The body is parsed with parse_float=Decimal so declared decimal-place limits can
be enforced exactly (money at most 2 decimals, ratios at most 4).
"""

import json
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import D

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parsed JSON object body; an absent body is treated as {}."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except ValueError:
        bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _present(data, name, required, default):
    if name not in data or data[name] is None:
        if required:
            bad("Field '%s' is required." % name)
        return (False, default)
    return (True, data[name])


def get_str(data, name, min_len=1, max_len=None, required=True, default=None):
    found, value = _present(data, name, required, default)
    if not found:
        return value
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value.strip()) < min_len:
        bad("Field '%s' must be at least %d characters and non-blank." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def get_bool(data, name, required=True, default=None):
    found, value = _present(data, name, required, default)
    if not found:
        return value
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def get_int(data, name, minimum=None, maximum=None, required=True, default=None):
    found, value = _present(data, name, required, default)
    if not found:
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    return value


def _as_decimal(name, value, max_places):
    if isinstance(value, bool):
        bad("Field '%s' must be a number." % name)
    if isinstance(value, Decimal):
        dec = value
    elif isinstance(value, int):
        dec = D(value)
    else:
        bad("Field '%s' must be a number." % name)
    try:
        exponent = dec.as_tuple().exponent
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % name)
    if not isinstance(exponent, int):
        bad("Field '%s' must be a finite number." % name)
    if max_places is not None and -exponent > max_places:
        bad("Field '%s' must carry at most %d decimal places." % (name, max_places))
    return dec


def get_money(data, name, minimum=None, maximum=None, exclusive_min=None,
              required=True, default=None):
    found, value = _present(data, name, required, default)
    if not found:
        return value
    dec = _as_decimal(name, value, 2)
    if exclusive_min is not None and dec <= D(exclusive_min):
        bad("Field '%s' must be greater than %s." % (name, exclusive_min))
    if minimum is not None and dec < D(minimum):
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and dec > D(maximum):
        bad("Field '%s' must be at most %s." % (name, maximum))
    return dec


def get_ratio(data, name, minimum=None, maximum=None, required=True, default=None,
              places=4):
    found, value = _present(data, name, required, default)
    if not found:
        return value
    dec = _as_decimal(name, value, places)
    if minimum is not None and dec < D(minimum):
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and dec > D(maximum):
        bad("Field '%s' must be at most %s." % (name, maximum))
    return dec


def get_number(data, name, minimum=None, maximum=None, required=True, default=None):
    found, value = _present(data, name, required, default)
    if not found:
        return value
    dec = _as_decimal(name, value, None)
    if minimum is not None and dec < D(minimum):
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and dec > D(maximum):
        bad("Field '%s' must be at most %s." % (name, maximum))
    return dec


def get_enum(data, name, allowed, required=True, default=None):
    found, value = _present(data, name, required, default)
    if not found:
        return value
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def get_date(data, name, required=True, default=None):
    found, value = _present(data, name, required, default)
    if not found:
        return value
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO date string (YYYY-MM-DD)." % name)
    try:
        return date.fromisoformat(value)
    except ValueError:
        bad("Field '%s' must be a valid ISO date (YYYY-MM-DD)." % name)


def get_id(data, name, required=True, default=None):
    found, value = _present(data, name, required, default)
    if not found:
        return value
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be a non-empty string identifier." % name)
    return value


def get_designations(data, name="designations", required=True):
    """The designations array: elements of { agency_id, designated_amount }."""
    if name not in data or data[name] is None:
        if required:
            bad("Field '%s' is required." % name)
        return None
    value = data[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    parsed = []
    for index, element in enumerate(value):
        if not isinstance(element, dict):
            bad("Element %d of '%s' must be an object." % (index, name))
        agency_id = get_id(element, "agency_id")
        amount = get_money(element, "designated_amount")
        parsed.append({"agency_id": agency_id, "designated_amount": amount})
    return parsed


def iso_date_str(value):
    return value.isoformat() if value is not None else None
