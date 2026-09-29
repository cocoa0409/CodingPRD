"""Payload shape validation (rank 13), level vocabulary (rank 15) helpers."""

from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from store import parse_instant

LEVEL_STEP = Decimal("0.5")
LEVEL_FLOOR = Decimal("2.5")
LEVEL_CEILING = Decimal("5.0")
LEVEL_VOCABULARY = [Decimal("2.5"), Decimal("3.0"), Decimal("3.5"),
                    Decimal("4.0"), Decimal("4.5"), Decimal("5.0")]


def bad(message=None):
    raise ApiError("ERR_VALIDATION", message)


def body():
    """Parsed JSON object body; anything but a JSON object is ERR_VALIDATION."""
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:
        payload = None
    if payload is None:
        if not request.get_data():
            return {}
        bad("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def reject_unknown(payload, allowed):
    for key in payload:
        if key not in allowed:
            bad("Unknown field: %s." % key)


def present(payload, field):
    return field in payload and payload[field] is not None


def req(payload, field):
    if field not in payload or payload[field] is None:
        bad("Field '%s' is required." % field)
    return payload[field]


def as_string(value, field, min_len=1, max_len=None):
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    text = value.strip()
    if len(text) < min_len:
        bad("Field '%s' must be at least %d characters." % (field, min_len))
    if max_len is not None and len(text) > max_len:
        bad("Field '%s' must be at most %d characters." % (field, max_len))
    return text


def req_string(payload, field, min_len=1, max_len=None):
    return as_string(req(payload, field), field, min_len, max_len)


def opt_string(payload, field, default=None, min_len=1, max_len=None):
    if not present(payload, field):
        return default
    return as_string(payload[field], field, min_len, max_len)


def as_int(value, field, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            bad("Field '%s' must be an integer." % field)
    if lo is not None and value < lo:
        bad("Field '%s' must be at least %s." % (field, lo))
    if hi is not None and value > hi:
        bad("Field '%s' must be at most %s." % (field, hi))
    return value


def req_int(payload, field, lo=None, hi=None):
    return as_int(req(payload, field), field, lo, hi)


def opt_int(payload, field, default=None, lo=None, hi=None):
    if not present(payload, field):
        return default
    return as_int(payload[field], field, lo, hi)


def req_bool(payload, field):
    value = req(payload, field)
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def opt_bool(payload, field, default=None):
    if not present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def req_enum(payload, field, choices):
    value = req(payload, field)
    if not isinstance(value, str) or value not in choices:
        bad("Field '%s' must be one of: %s." % (field, ", ".join(choices)))
    return value


def opt_enum(payload, field, choices, default=None):
    if not present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in choices:
        bad("Field '%s' must be one of: %s." % (field, ", ".join(choices)))
    return value


def req_instant(payload, field):
    raw = req(payload, field)
    if not isinstance(raw, str):
        bad("Field '%s' must be an ISO 8601 UTC instant." % field)
    parsed = parse_instant(raw)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC instant." % field)
    return parsed


def opt_instant(payload, field, default=None):
    if not present(payload, field):
        return default
    return req_instant(payload, field)


def req_id(payload, field):
    value = req(payload, field)
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be a non-empty identifier string." % field)
    return value.strip()


def opt_id(payload, field, default=None):
    if not present(payload, field):
        return default
    return req_id(payload, field)


# ------------------------------------------------------------------ levels ---

def req_numeric(payload, field):
    value = req(payload, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % field)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % field)


def check_level(value):
    """Rank 15 — the six-member NTRP vocabulary."""
    if value is None:
        raise ApiError("ERR_INVALID_RATING_LEVEL")
    if value < LEVEL_FLOOR or value > LEVEL_CEILING:
        raise ApiError("ERR_INVALID_RATING_LEVEL")
    if (value / LEVEL_STEP) % 1 != 0:
        raise ApiError("ERR_INVALID_RATING_LEVEL")
    return value


def req_level(payload, field):
    """Numeric shape at rank 13, vocabulary membership at rank 15."""
    return req_numeric(payload, field)


def level_out(value):
    if value is None:
        return None
    return float(value)


def to_level(value):
    if value is None:
        return None
    return Decimal(str(value))
