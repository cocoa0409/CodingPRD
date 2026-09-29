"""Request-body shape validation (PRD Section 2.6 check 8)."""
from decimal import Decimal, InvalidOperation

from flask import request

import store
from errors import ApiError


def bad(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise bad("Request body must be a JSON object.")
    if not isinstance(data, dict):
        raise bad("Request body must be a JSON object.")
    return data


def present(body, key):
    return key in body and body[key] is not None


def _missing(key):
    raise bad("Field '%s' is required." % key)


def str_field(body, key, required=True, min_len=1, max_len=None, default=None,
              allow_blank=False):
    if not present(body, key):
        if required:
            _missing(key)
        return default
    value = body[key]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % key)
    if not allow_blank and not value.strip():
        raise bad("Field '%s' must not be blank." % key)
    if min_len is not None and len(value) < min_len:
        raise bad("Field '%s' is shorter than %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' is longer than %d characters." % (key, max_len))
    return value


def enum_field(body, key, allowed, required=True, default=None):
    if not present(body, key):
        if required:
            _missing(key)
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def int_field(body, key, lo=None, hi=None, required=True, default=None):
    if not present(body, key):
        if required:
            _missing(key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % key)
    if lo is not None and value < lo:
        raise bad("Field '%s' must be at least %d." % (key, lo))
    if hi is not None and value > hi:
        raise bad("Field '%s' must be at most %d." % (key, hi))
    return value


def dec_field(body, key, lo=None, hi=None, required=True, default=None,
              places=2, exclusive_lo=False):
    if not present(body, key):
        if required:
            _missing(key)
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % key)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        raise bad("Field '%s' must be a number." % key)
    if lo is not None:
        if exclusive_lo and dec <= lo:
            raise bad("Field '%s' must be greater than %s." % (key, lo))
        if not exclusive_lo and dec < lo:
            raise bad("Field '%s' must be at least %s." % (key, lo))
    if hi is not None and dec > hi:
        raise bad("Field '%s' must be at most %s." % (key, hi))
    if places is not None:
        dec = dec.quantize(Decimal(1).scaleb(-places))
    return dec


def bool_field(body, key, required=True, default=None):
    if not present(body, key):
        if required:
            _missing(key)
        return default
    value = body[key]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % key)
    return value


def date_field(body, key, required=True, default=None):
    if not present(body, key):
        if required:
            _missing(key)
        return default
    value = body[key]
    parsed = store.parse_date(value)
    if parsed is None:
        raise bad("Field '%s' must be a date in YYYY-MM-DD form." % key)
    return value


def datetime_field(body, key, required=True, default=None):
    if not present(body, key):
        if required:
            _missing(key)
        return default
    value = body[key]
    parsed = store.parse_iso(value)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 datetime." % key)
    return parsed


def id_field(body, key, required=True, default=None):
    if not present(body, key):
        if required:
            _missing(key)
        return default
    value = body[key]
    if not isinstance(value, str) or not value.strip():
        raise bad("Field '%s' must be a non-empty string." % key)
    return value


def enum_list_field(body, key, allowed, required=True, default=None,
                    min_len=0, max_len=None):
    if not present(body, key):
        if required:
            _missing(key)
        return list(default) if isinstance(default, list) else default
    value = body[key]
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % key)
    if min_len is not None and len(value) < min_len:
        raise bad("Field '%s' must hold at least %d entries." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' must hold at most %d entries." % (key, max_len))
    seen = set()
    for item in value:
        if not isinstance(item, str) or (allowed is not None and item not in allowed):
            raise bad("Field '%s' holds an unrecognized entry." % key)
        if not item.strip():
            raise bad("Field '%s' holds a blank entry." % key)
        if item in seen:
            raise bad("Field '%s' must not contain duplicates." % key)
        seen.add(item)
    return list(value)
