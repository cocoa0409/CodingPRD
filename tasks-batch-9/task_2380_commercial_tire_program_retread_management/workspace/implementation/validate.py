"""Request body / query shape validation (PRD §2.11 step 6 -> ERR_INVALID_REQUEST)."""

from decimal import Decimal, InvalidOperation

from flask import request

import errors
from errors import fail
from util import dec, parse_date, parse_datetime

_MISSING = object()


def bad(field=None):
    msg = "Invalid or missing field: %s" % field if field else "The request is malformed."
    fail(errors.ERR_INVALID_REQUEST, msg)


def body():
    if request.data in (None, b"", ""):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        bad("body")
    if not isinstance(data, dict):
        bad("body")
    return data


def present(payload, key):
    return key in payload and payload[key] is not None


def _get(payload, key, required):
    if key not in payload or payload[key] is None:
        if required:
            bad(key)
        return _MISSING
    return payload[key]


def s_str(payload, key, required=True, allow_empty=False, min_len=None, max_len=None):
    value = _get(payload, key, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str):
        bad(key)
    if not allow_empty and value == "":
        bad(key)
    if min_len is not None and len(value) < min_len:
        bad(key)
    if max_len is not None and len(value) > max_len:
        bad(key)
    return value


def s_int(payload, key, required=True, minimum=None, maximum=None):
    value = _get(payload, key, required)
    if value is _MISSING:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        bad(key)
    if minimum is not None and value < minimum:
        bad(key)
    if maximum is not None and value > maximum:
        bad(key)
    return value


def s_num(payload, key, required=True, minimum=None, maximum=None, max_decimals=None):
    value = _get(payload, key, required)
    if value is _MISSING:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(key)
    try:
        value_dec = dec(value)
    except (InvalidOperation, ValueError):
        bad(key)
    if minimum is not None and value_dec < dec(minimum):
        bad(key)
    if maximum is not None and value_dec > dec(maximum):
        bad(key)
    if max_decimals is not None and -value_dec.normalize().as_tuple().exponent > max_decimals:
        bad(key)
    return value_dec


def s_bool(payload, key, required=True):
    value = _get(payload, key, required)
    if value is _MISSING:
        return None
    if not isinstance(value, bool):
        bad(key)
    return value


def s_enum(payload, key, members, required=True):
    value = _get(payload, key, required)
    if value is _MISSING:
        return None
    if not isinstance(value, str) or value not in members:
        bad(key)
    return value


def s_datetime(payload, key, required=True):
    """Returns (raw_string, datetime) so responses can echo exactly what was sent."""
    value = _get(payload, key, required)
    if value is _MISSING:
        return None, None
    parsed = parse_datetime(value)
    if parsed is None:
        bad(key)
    return value, parsed


def s_date(payload, key, required=True):
    value = _get(payload, key, required)
    if value is _MISSING:
        return None, None
    parsed = parse_date(value)
    if parsed is None:
        bad(key)
    return value, parsed


def s_str_array(payload, key, required=True, non_empty=True):
    value = _get(payload, key, required)
    if value is _MISSING:
        return None
    if not isinstance(value, list):
        bad(key)
    if non_empty and len(value) == 0:
        bad(key)
    for item in value:
        if not isinstance(item, str) or item == "":
            bad(key)
    return list(value)


def s_quarter_hours(payload, key, required=True, minimum=0, maximum=24):
    value = s_num(payload, key, required=required, minimum=minimum, maximum=maximum)
    if value is None:
        return None
    if (value / Decimal("0.25")) % 1 != 0:
        bad(key)
    return value


# ---------------------------------------------------------------- query params

def q_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            bad("limit")
        if str(limit) != limit_raw.strip():
            bad("limit")
        if limit < 1 or limit > 100:
            bad("limit")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            bad("offset")
        if str(offset) != offset_raw.strip():
            bad("offset")
        if offset < 0:
            bad("offset")
    return limit, offset


def q_str(key):
    value = request.args.get(key)
    if value is None:
        return None
    return value


def q_enum(key, members):
    value = request.args.get(key)
    if value is None:
        return None
    if value not in members:
        bad(key)
    return value


def q_bool(key):
    value = request.args.get(key)
    if value is None:
        return None
    low = value.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    bad(key)
