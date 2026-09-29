"""Band-5 request-shape validation helpers (PRD 2.10 band 5).

Every helper raises ERR_INVALID_REQUEST; unknown body fields are ignored.
"""
from decimal import Decimal

from flask import request

from db import parse_iso
from errors import ApiError

SENTINEL = object()


def bad():
    raise ApiError("ERR_INVALID_REQUEST")


def peek_body():
    """Body as a dict for pre-shape bands; never raises."""
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def get_body():
    raw = request.get_data() or b""
    if not raw.strip():
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        bad()
    if not isinstance(data, dict):
        bad()
    return data


# --------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------
def req_str(body, key, max_len=None, min_len=1):
    value = body.get(key, SENTINEL)
    if value is SENTINEL or value is None:
        bad()
    if not isinstance(value, str):
        bad()
    if len(value) < min_len:
        bad()
    if max_len is not None and len(value) > max_len:
        bad()
    return value


def opt_str(body, key, max_len=None):
    value = body.get(key, SENTINEL)
    if value is SENTINEL or value is None:
        return None
    if not isinstance(value, str) or not value:
        bad()
    if max_len is not None and len(value) > max_len:
        bad()
    return value


def must_be_absent(body, key):
    value = body.get(key, SENTINEL)
    if value is SENTINEL or value is None:
        return
    bad()


# --------------------------------------------------------------------------
# enums
# --------------------------------------------------------------------------
def req_enum(body, key, allowed):
    value = req_str(body, key)
    if value not in allowed:
        bad()
    return value


def opt_enum(body, key, allowed):
    value = opt_str(body, key)
    if value is None:
        return None
    if value not in allowed:
        bad()
    return value


# --------------------------------------------------------------------------
# integers
# --------------------------------------------------------------------------
def _as_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        bad()
    return value


def req_int(body, key, minimum=0, maximum=None):
    value = body.get(key, SENTINEL)
    if value is SENTINEL or value is None:
        bad()
    value = _as_int(value)
    if minimum is not None and value < minimum:
        bad()
    if maximum is not None and value > maximum:
        bad()
    return value


def opt_int(body, key, minimum=0, maximum=None):
    value = body.get(key, SENTINEL)
    if value is SENTINEL or value is None:
        return None
    return req_int(body, key, minimum, maximum)


# --------------------------------------------------------------------------
# money / decimals
# --------------------------------------------------------------------------
def _as_decimal(value, places):
    if isinstance(value, bool):
        bad()
    if not isinstance(value, (int, float)):
        bad()
    try:
        dec = Decimal(str(value))
    except Exception:
        bad()
    if not dec.is_finite():
        bad()
    exponent = dec.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -places:
        bad()
    return dec


def req_money(body, key, positive=False, places=2):
    value = body.get(key, SENTINEL)
    if value is SENTINEL or value is None:
        bad()
    dec = _as_decimal(value, places)
    if positive:
        if dec <= 0:
            bad()
    elif dec < 0:
        bad()
    return dec


def opt_money(body, key, positive=False, places=2):
    value = body.get(key, SENTINEL)
    if value is SENTINEL or value is None:
        return None
    return req_money(body, key, positive, places)


# --------------------------------------------------------------------------
# datetimes / booleans / arrays
# --------------------------------------------------------------------------
def req_dt(body, key):
    value = body.get(key, SENTINEL)
    if value is SENTINEL or value is None:
        bad()
    if not isinstance(value, str):
        bad()
    parsed = parse_iso(value)
    if parsed is None:
        bad()
    return parsed


def opt_dt(body, key):
    value = body.get(key, SENTINEL)
    if value is SENTINEL or value is None:
        return None
    return req_dt(body, key)


def opt_bool(body, key, default=None):
    value = body.get(key, SENTINEL)
    if value is SENTINEL or value is None:
        return default
    if not isinstance(value, bool):
        bad()
    return value


def req_list(body, key):
    value = body.get(key, SENTINEL)
    if value is SENTINEL or value is None:
        bad()
    if not isinstance(value, list):
        bad()
    return value
