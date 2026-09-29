"""Rung 4 of PRD §2.9 — body shape.  Every field with no declared default must be
present; supplied values must match their declared type; enum values must be declared
members; volumes/counts and money/rates must be non-negative; and every supplied
interval must have its start strictly before its end."""
from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import bad_request
from numeric import D

MISSING = object()


def body():
    data = request.get_json(silent=True)
    if data is None:
        if request.data:
            raise bad_request("Request body must be a JSON object.")
        return {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object.")
    return data


def raw(payload, field):
    return payload.get(field, MISSING)


def _present(payload, field, required):
    value = payload.get(field, MISSING)
    if value is MISSING or value is None:
        if required:
            raise bad_request("Field '%s' is required." % field)
        return MISSING
    return value


def string_field(payload, field, required=True, default=None, min_len=None, max_len=None,
                 pattern=None):
    value = _present(payload, field, required)
    if value is MISSING:
        return default
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % field)
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field '%s' is too short." % field)
    if max_len is not None and len(value) > max_len:
        raise bad_request("Field '%s' is too long." % field)
    if pattern is not None and not pattern.match(value):
        raise bad_request("Field '%s' is malformed." % field)
    return value


def bool_field(payload, field, required=True, default=None):
    value = _present(payload, field, required)
    if value is MISSING:
        return default
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % field)
    return value


def int_field(payload, field, required=True, default=None, minimum=0, maximum=None):
    value = _present(payload, field, required)
    if value is MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' is below its minimum." % field)
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' is above its maximum." % field)
    return value


def dec_field(payload, field, required=True, default=None, minimum=Decimal("0"),
              maximum=None, exclusive_min=False):
    value = _present(payload, field, required)
    if value is MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise bad_request("Field '%s' must be a number." % field)
    try:
        number = D(value)
    except (InvalidOperation, ValueError, ArithmeticError):
        raise bad_request("Field '%s' must be a number." % field)
    if not number.is_finite():
        raise bad_request("Field '%s' must be a finite number." % field)
    if minimum is not None:
        if exclusive_min and number <= minimum:
            raise bad_request("Field '%s' must be greater than %s." % (field, minimum))
        if not exclusive_min and number < minimum:
            raise bad_request("Field '%s' must not be below %s." % (field, minimum))
    if maximum is not None and number > maximum:
        raise bad_request("Field '%s' must not exceed %s." % (field, maximum))
    return number


def enum_field(payload, field, members, required=True, default=None):
    value = _present(payload, field, required)
    if value is MISSING:
        return default
    if not isinstance(value, str) or value not in members:
        raise bad_request("Field '%s' must be one of %s." % (field, ", ".join(members)))
    return value


def enum_list_field(payload, field, members, required=True, default=None,
                    non_empty=True):
    value = _present(payload, field, required)
    if value is MISSING:
        return default
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array." % field)
    if non_empty and not value:
        raise bad_request("Field '%s' must not be empty." % field)
    for item in value:
        if not isinstance(item, str) or item not in members:
            raise bad_request("Field '%s' may only contain %s."
                              % (field, ", ".join(members)))
    return value


def dt_field(payload, field, required=True, default=None):
    """Validates the instant and returns the supplied string verbatim, so an echoed
    input keeps the precision at which it was supplied."""
    value = _present(payload, field, required)
    if value is MISSING:
        return default
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be an ISO 8601 timestamp." % field)
    store.parse_dt(value)
    return value


def id_field(payload, field, required=True, default=None):
    value = _present(payload, field, required)
    if value is MISSING:
        return default
    if not isinstance(value, str) or not value:
        raise bad_request("Field '%s' must be an identifier string." % field)
    return value


def interval(start, end, start_name, end_name):
    if start is None or end is None:
        return
    if store.parse_dt(start) >= store.parse_dt(end):
        raise bad_request("%s must be strictly before %s." % (start_name, end_name))
