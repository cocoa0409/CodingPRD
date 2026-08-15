"""Request-shape validation helpers (validation band 1 -> ERR_VALIDATION 400)
plus date/datetime parsing and Decimal conversion utilities."""
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import request

from errors import ApiError

TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")


def round2(x):
    return Decimal(x).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round4(x):
    return Decimal(x).quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def _err(message):
    return ApiError("ERR_VALIDATION", 400, message)


def get_body():
    """Parse the request JSON body into a dict; numbers keep decimal precision."""
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    try:
        body = json.loads(raw, parse_float=Decimal)
    except (ValueError, InvalidOperation):
        raise _err("Request body is not well-formed JSON")
    if not isinstance(body, dict):
        raise _err("Request body must be a JSON object")
    return body


def is_number(v):
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def to_decimal(v):
    if isinstance(v, Decimal):
        return v
    if isinstance(v, int):
        return Decimal(v)
    # float fallback (should not occur: json parsed with parse_float=Decimal)
    return Decimal(str(v))


def has_field(body, key):
    return key in body


def req_string(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        raise _err("Field '%s' is required and must be a string" % key)
    return v


def opt_string(body, key):
    v = body.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise _err("Field '%s' must be a string" % key)
    return v


def req_number(body, key):
    v = body.get(key)
    if not is_number(v):
        raise _err("Field '%s' is required and must be a number" % key)
    return to_decimal(v)


def opt_number(body, key):
    v = body.get(key)
    if v is None:
        return None
    if not is_number(v):
        raise _err("Field '%s' must be a number" % key)
    return to_decimal(v)


def req_int(body, key):
    v = body.get(key)
    if isinstance(v, bool):
        raise _err("Field '%s' is required and must be an integer" % key)
    if isinstance(v, int):
        return v
    if isinstance(v, (float, Decimal)) and Decimal(str(v)) == int(Decimal(str(v))):
        return int(Decimal(str(v)))
    raise _err("Field '%s' is required and must be an integer" % key)


def req_enum(body, key, allowed):
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        raise _err("Field '%s' must be one of %s" % (key, sorted(allowed)))
    return v


def require_positive(value, key):
    if value <= 0:
        raise _err("Field '%s' must be greater than 0" % key)
    return value


def require_nonnegative(value, key):
    if value < 0:
        raise _err("Field '%s' must be non-negative" % key)
    return value


def require_range(value, key, lo, hi):
    if value < lo or value > hi:
        raise _err("Field '%s' must be within [%s, %s]" % (key, lo, hi))
    return value


def parse_date_value(v, key):
    if not isinstance(v, str):
        raise _err("Field '%s' must be an ISO date string" % key)
    try:
        return date.fromisoformat(v.strip())
    except ValueError:
        raise _err("Field '%s' must be an ISO date string" % key)


def req_date(body, key):
    return parse_date_value(body.get(key), key)


def parse_datetime_value(v, key):
    if not isinstance(v, str):
        raise _err("Field '%s' must be an ISO 8601 datetime string" % key)
    s = v.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise _err("Field '%s' must be an ISO 8601 datetime string" % key)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(body, key):
    return parse_datetime_value(body.get(key), key)
