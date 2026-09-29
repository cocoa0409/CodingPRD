"""Payload shape validation -- rung 7 of the ladder (ERR_INVALID_REQUEST, 422).

An explicitly supplied JSON null is treated exactly like an omitted field, so an
optional field with a declared default falls back to that default and a nullable
optional field stays null.
"""

from decimal import Decimal, InvalidOperation

from flask import request

from core import dec, parse_iso
from errors import fail


def json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def has(data, field):
    return field in data and data.get(field) is not None


def raw(data, field):
    return data.get(field)


def bad(field, detail):
    fail("ERR_INVALID_REQUEST", "%s %s" % (field, detail))


# ---------------------------------------------------------------------------
# scalar coercion
# ---------------------------------------------------------------------------

def _to_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != int(value):
            return None
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _to_dec(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, Decimal)):
        return dec(value)
    if isinstance(value, float):
        return dec(value)
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            return Decimal(text)
        except InvalidOperation:
            return None
    return None


# ---------------------------------------------------------------------------
# field readers
# ---------------------------------------------------------------------------

def string_field(data, field, required=False, default=None, min_len=1, max_len=None):
    if not has(data, field):
        if required:
            bad(field, "is required.")
        return default
    value = data[field]
    if not isinstance(value, str):
        bad(field, "must be a string.")
    if value.strip() == "" and min_len >= 1:
        bad(field, "may not be blank.")
    if min_len is not None and len(value) < min_len:
        bad(field, "must be at least %d characters." % min_len)
    if max_len is not None and len(value) > max_len:
        bad(field, "must be at most %d characters." % max_len)
    return value


def int_field(data, field, required=False, default=None, minimum=None, maximum=None,
              allowed=None):
    if not has(data, field):
        if required:
            bad(field, "is required.")
        return default
    value = _to_int(data[field])
    if value is None:
        bad(field, "must be an integer.")
    if minimum is not None and value < minimum:
        bad(field, "must be at least %d." % minimum)
    if maximum is not None and value > maximum:
        bad(field, "must be at most %d." % maximum)
    if allowed is not None and value not in allowed:
        bad(field, "must be one of %s." % sorted(allowed))
    return value


def dec_field(data, field, required=False, default=None, minimum=None, maximum=None,
              exclusive_minimum=None):
    if not has(data, field):
        if required:
            bad(field, "is required.")
        return default
    value = _to_dec(data[field])
    if value is None or not value.is_finite():
        bad(field, "must be a decimal number.")
    if minimum is not None and value < dec(minimum):
        bad(field, "must be at least %s." % minimum)
    if maximum is not None and value > dec(maximum):
        bad(field, "must be at most %s." % maximum)
    if exclusive_minimum is not None and value <= dec(exclusive_minimum):
        bad(field, "must be greater than %s." % exclusive_minimum)
    return value


def enum_field(data, field, members, required=False, default=None):
    if not has(data, field):
        if required:
            bad(field, "is required.")
        return default
    value = data[field]
    if not isinstance(value, str) or value not in members:
        bad(field, "must be one of %s." % list(members))
    return value


def bool_field(data, field, required=False, default=None):
    if not has(data, field):
        if required:
            bad(field, "is required.")
        return default
    value = data[field]
    if not isinstance(value, bool):
        bad(field, "must be a boolean.")
    return value


def datetime_field(data, field, required=False, default=None):
    if not has(data, field):
        if required:
            bad(field, "is required.")
        return default
    value = data[field]
    if not isinstance(value, str):
        bad(field, "must be an ISO 8601 UTC timestamp string.")
    moment = parse_iso(value)
    if moment is None:
        bad(field, "must be a valid ISO 8601 UTC timestamp.")
    return moment


def require_window(start, end):
    """Rung 8: window_start must be strictly earlier than window_end."""
    if start is None or end is None:
        return
    if not start < end:
        fail("ERR_INVALID_WINDOW", "window_start must be strictly earlier than window_end.")
