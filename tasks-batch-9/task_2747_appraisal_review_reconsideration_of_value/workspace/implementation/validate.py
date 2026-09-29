"""Request body shape validation (ladder rung 8) and numeric helpers.

Unknown fields are silently ignored.  A required field that is absent, a
declared enumeration value out of range, a negative integer where a
non-negative one is required, or a timestamp that is not ISO 8601 with a Z
suffix all raise ERR_INVALID_REQUEST.
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

from errors import fail


# ------------------------------------------------------------------- numerics
def rhu(numerator, denominator=1):
    """Round half up to the nearest integer."""
    value = Decimal(numerator) / Decimal(denominator)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps_of(part, whole):
    """round_half_up(10000 * part / whole)."""
    return rhu(Decimal(10000) * Decimal(part), Decimal(whole))


# ----------------------------------------------------------------- body input
def body():
    payload = request.get_json(silent=True)
    if payload is None:
        if request.data and request.data.strip():
            fail("ERR_INVALID_REQUEST")
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST")
    return payload


def present(data, field):
    return field in data and data[field] is not None


def req_str(data, field, min_len=1, max_len=None):
    if not present(data, field):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % field)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % field)
    return value


def opt_str(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    return value


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a permitted value." % field)
    return value


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    return req_enum(data, field, allowed)


def _as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    return value


def req_int(data, field, minimum=None, positive=False):
    if not present(data, field):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = _as_int(data[field], field)
    if positive and value <= 0:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be greater than zero." % field)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below the permitted minimum." % field)
    return value


def opt_int(data, field, default=None, minimum=None, positive=False):
    if not present(data, field):
        return default
    return req_int(data, field, minimum=minimum, positive=positive)


def req_bool(data, field, default=None):
    if not present(data, field):
        if default is None:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
        return default
    value = data[field]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return value


def parse_dt(value, field):
    if not isinstance(value, str) or value == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp." % field)
    text = value.strip()
    body_text = text
    if text.endswith("Z"):
        body_text = text[:-1]
    elif text.endswith("+00:00"):
        body_text = text[:-6]
    else:
        fail("ERR_INVALID_REQUEST", "Field '%s' must carry a Z suffix." % field)
    try:
        if "T" in body_text:
            parsed = datetime.fromisoformat(body_text)
        else:
            parsed = datetime.fromisoformat(body_text + "T00:00:00")
    except ValueError:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a valid ISO 8601 timestamp." % field)
    return parsed.replace(tzinfo=timezone.utc)


def req_dt(data, field):
    if not present(data, field):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    return parse_dt(data[field], field)


def opt_dt(data, field, default=None):
    if not present(data, field):
        return default
    return parse_dt(data[field], field)


def req_decimal_2dp(data, field, minimum=None):
    if not present(data, field):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    return _decimal_2dp(data[field], field, minimum)


def opt_decimal_2dp(data, field, default=None, minimum=None):
    if not present(data, field):
        return default
    return _decimal_2dp(data[field], field, minimum)


def _decimal_2dp(value, field, minimum):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)
    if dec != dec.quantize(Decimal("0.01")):
        fail("ERR_INVALID_REQUEST", "Field '%s' carries more than two decimal places." % field)
    dec = dec.quantize(Decimal("0.01"))
    if minimum is not None and dec < Decimal(minimum):
        fail("ERR_INVALID_REQUEST", "Field '%s' is below the permitted minimum." % field)
    return dec


def req_state_code(data, field):
    value = req_str(data, field)
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a two letter uppercase state code." % field)
    return value


def req_enum_list(data, field, allowed):
    if not present(data, field):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % field)
    seen = set()
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            fail("ERR_INVALID_REQUEST", "Field '%s' holds an unrecognized member." % field)
        if item in seen:
            fail("ERR_INVALID_REQUEST", "Field '%s' holds duplicate members." % field)
        seen.add(item)
    return list(value)


# ------------------------------------------------------------- query helpers
def query_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None


def query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None
