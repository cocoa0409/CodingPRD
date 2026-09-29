"""Payload shape validation.  Every violation here is ERR_INVALID_REQUEST (400).

PRD §2.8 step 5: request-shape rejection sits behind existence and ownership and
ahead of every domain-specific rejection, so callers wire these checks into the
shared precedence pipeline at rank 14.
"""

from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import ApiError


def raw_body():
    """Parsed JSON object, or None when the body is absent / not a JSON object."""
    data = request.get_json(silent=True, force=True)
    if isinstance(data, dict):
        return data
    return None


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def _present(body, name):
    return name in body and body[name] is not None


def string_field(body, name, required=True, min_len=1, max_len=None, default=None):
    if not _present(body, name):
        if required:
            _bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value.strip()) < min_len:
        _bad("Field '%s' must not be blank." % name)
    if min_len is not None and len(value) < min_len:
        _bad("Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        _bad("Field '%s' is too long." % name)
    return value


def enum_field(body, name, values, required=True, default=None):
    if not _present(body, name):
        if required:
            _bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in values:
        _bad("Field '%s' must be one of %s." % (name, ", ".join(values)))
    return value


def int_field(body, name, required=True, minimum=None, maximum=None, default=None):
    if not _present(body, name):
        if required:
            _bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            _bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be <= %s." % (name, maximum))
    return value


def bool_field(body, name, required=False, default=False):
    if not _present(body, name):
        if required:
            _bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % name)
    return value


def decimal_field(body, name, required=True, minimum=None, maximum=None,
                  exclusive_min=False, places=None, default=None):
    if not _present(body, name):
        if required:
            _bad("Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        _bad("Field '%s' must be a number." % name)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad("Field '%s' must be a number." % name)
    if dec != dec:  # NaN
        _bad("Field '%s' must be a number." % name)
    if places is not None and -dec.as_tuple().exponent > places:
        _bad("Field '%s' allows at most %d decimal places." % (name, places))
    if minimum is not None:
        if exclusive_min and dec <= Decimal(str(minimum)):
            _bad("Field '%s' must be greater than %s." % (name, minimum))
        if not exclusive_min and dec < Decimal(str(minimum)):
            _bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and dec > Decimal(str(maximum)):
        _bad("Field '%s' must be <= %s." % (name, maximum))
    return dec


def instant_field(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            _bad("Field '%s' is required." % name)
        return default
    parsed = store.parse_instant(body[name])
    if parsed is None:
        _bad("Field '%s' must be an ISO 8601 UTC instant." % name)
    return parsed


def day_field(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            _bad("Field '%s' is required." % name)
        return default
    parsed = store.parse_day(body[name])
    if parsed is None:
        _bad("Field '%s' must be a calendar date (YYYY-MM-DD)." % name)
    return parsed


def id_list_field(body, name, required=True):
    if not _present(body, name):
        if required:
            _bad("Field '%s' is required." % name)
        return []
    value = body[name]
    if not isinstance(value, list):
        _bad("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _bad("Field '%s' must contain identifier strings." % name)
    return value


def object_list_field(body, name, required=True):
    if not _present(body, name):
        if required:
            _bad("Field '%s' is required." % name)
        return []
    value = body[name]
    if not isinstance(value, list):
        _bad("Field '%s' must be an array." % name)
    for item in value:
        if not isinstance(item, dict):
            _bad("Field '%s' must contain objects." % name)
    return value


def country_code_field(body, name):
    value = string_field(body, name, required=True, min_len=2, max_len=2)
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        _bad("Field '%s' must be a two-letter uppercase country code." % name)
    return value


def email_field(body, name):
    value = string_field(body, name, required=True, min_len=3, max_len=254)
    if value.count("@") != 1 or value.startswith("@") or value.endswith("@"):
        _bad("Field '%s' must be an email address." % name)
    return value


def raw_string(body, name):
    """Presence-only read used by existence checks that run ahead of rank 14."""
    if body is None:
        return None
    value = body.get(name)
    if isinstance(value, str) and value.strip():
        return value
    return None
