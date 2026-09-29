"""Rung 6 of the ladder: request shape, enum membership and range checks."""

from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import ApiError

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON request body as a dict; an absent body is an empty object."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def present(b, key):
    return key in b and b[key] is not None


def _get(b, key, required):
    if key not in b or b[key] is None:
        if required:
            bad("Field '%s' is required." % key)
        return _MISSING
    return b[key]


def str_field(b, key, required=True, min_len=1, max_len=None, default=None):
    raw = _get(b, key, required)
    if raw is _MISSING:
        return default
    if not isinstance(raw, str):
        bad("Field '%s' must be a string." % key)
    if len(raw) < min_len:
        bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(raw) > max_len:
        bad("Field '%s' must be at most %d characters." % (key, max_len))
    return raw


def enum_field(b, key, allowed, required=True, default=None):
    raw = _get(b, key, required)
    if raw is _MISSING:
        return default
    if not isinstance(raw, str) or raw not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return raw


def int_field(b, key, required=True, minimum=None, maximum=None, default=None):
    raw = _get(b, key, required)
    if raw is _MISSING:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and raw < minimum:
        bad("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and raw > maximum:
        bad("Field '%s' must be at most %s." % (key, maximum))
    return raw


def bool_field(b, key, required=True, default=None):
    raw = _get(b, key, required)
    if raw is _MISSING:
        return default
    if not isinstance(raw, bool):
        bad("Field '%s' must be a boolean." % key)
    return raw


def decimal_field(b, key, required=True, minimum=None, maximum=None, default=None, places=4):
    raw = _get(b, key, required)
    if raw is _MISSING:
        return default
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str, Decimal)):
        bad("Field '%s' must be a number." % key)
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % key)
    if not value.is_finite():
        bad("Field '%s' must be a finite number." % key)
    if minimum is not None and value < Decimal(str(minimum)):
        bad("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and value > Decimal(str(maximum)):
        bad("Field '%s' must be at most %s." % (key, maximum))
    return db.round_money(value, places)


def date_field(b, key, required=True, default=None):
    """Returns (iso_text, date) or (default, None)."""
    raw = _get(b, key, required)
    if raw is _MISSING:
        return default, None
    if not isinstance(raw, str):
        bad("Field '%s' must be a YYYY-MM-DD date string." % key)
    parsed = db.parse_date(raw)
    if parsed is None:
        bad("Field '%s' must be a valid YYYY-MM-DD date." % key)
    return raw, parsed


def ts_field(b, key, required=True, default=None):
    """Returns (iso_text, datetime) or (default, None)."""
    raw = _get(b, key, required)
    if raw is _MISSING:
        return default, None
    if not isinstance(raw, str):
        bad("Field '%s' must be an ISO 8601 timestamp." % key)
    parsed = db.parse_ts(raw)
    if parsed is None or "T" not in raw:
        bad("Field '%s' must be a valid ISO 8601 timestamp." % key)
    return raw, parsed


def obj_field(b, key, required=True, default=None):
    raw = _get(b, key, required)
    if raw is _MISSING:
        return default
    if not isinstance(raw, dict):
        bad("Field '%s' must be an object." % key)
    return raw


def list_field(b, key, required=True, min_len=1, max_len=None, allowed=None, default=None):
    raw = _get(b, key, required)
    if raw is _MISSING:
        return default
    if not isinstance(raw, list):
        bad("Field '%s' must be an array." % key)
    if len(raw) < min_len:
        bad("Field '%s' must contain at least %d entries." % (key, min_len))
    if max_len is not None and len(raw) > max_len:
        bad("Field '%s' must contain at most %d entries." % (key, max_len))
    if allowed is not None:
        for item in raw:
            if not isinstance(item, str) or item not in allowed:
                bad("Field '%s' contains an unsupported value." % key)
    return raw


def id_field(b, key, required=True, default=None):
    raw = _get(b, key, required)
    if raw is _MISSING:
        return default
    if not isinstance(raw, str) or not raw.strip():
        bad("Field '%s' must be an identifier string." % key)
    return raw


def query_enum(name, allowed, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if raw not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return raw
