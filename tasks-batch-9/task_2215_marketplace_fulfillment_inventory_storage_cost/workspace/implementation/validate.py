"""Request body shape validation — PRD §2.6 ladder step 3 (ERR_INVALID_REQUEST)."""
from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import ApiError


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", 400, message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, required=True, non_empty=True):
    if not present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return None
    value = data[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if non_empty and value.strip() == "":
        bad("Field '%s' must be a non-empty string." % key)
    return value


def req_int(data, key, required=True, minimum=None, maximum=None):
    if not present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return None
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (key, maximum))
    return value


def req_num(data, key, required=True, minimum=None, maximum=None,
            exclusive_minimum=None):
    if not present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return None
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad("Field '%s' must be a number." % key)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % key)
    if not dec.is_finite():
        bad("Field '%s' must be a finite number." % key)
    if exclusive_minimum is not None and dec <= Decimal(str(exclusive_minimum)):
        bad("Field '%s' must be > %s." % (key, exclusive_minimum))
    if minimum is not None and dec < Decimal(str(minimum)):
        bad("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        bad("Field '%s' must be <= %s." % (key, maximum))
    return dec


def req_bool(data, key, required=True):
    if not present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return None
    value = data[key]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def req_enum(data, key, allowed, required=True):
    if not present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return None
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def req_dt(data, key, required=True):
    if not present(data, key):
        if required:
            bad("Field '%s' is required." % key)
        return None
    parsed = clock.parse(data[key])
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 timestamp." % key)
    return parsed


def opt_str(data, key):
    if not present(data, key):
        return None
    if not isinstance(data[key], str):
        bad("Field '%s' must be a string." % key)
    return data[key]
