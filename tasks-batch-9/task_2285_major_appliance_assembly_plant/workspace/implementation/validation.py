"""Schema validation helpers (validation ladder priority 3 — ERR_INVALID_REQUEST)."""

import json
import math
import re
from datetime import datetime, timedelta, timezone

from errors import ApiError, invalid
from flask import request

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


# --------------------------------------------------------------------------- #
# body / query access
# --------------------------------------------------------------------------- #
def body():
    raw = request.get_data()
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise invalid("Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid("Request body must be a JSON object")
    return data


def has(b, key):
    return key in b and b[key] is not None


# --------------------------------------------------------------------------- #
# scalar field helpers
# --------------------------------------------------------------------------- #
def _missing(key):
    raise invalid("Field '%s' is required" % key)


def req_str(b, key, min_len=1, max_len=None):
    if not has(b, key):
        _missing(key)
    v = b[key]
    if not isinstance(v, str):
        raise invalid("Field '%s' must be a string" % key)
    if len(v) < min_len:
        raise invalid("Field '%s' is too short" % key)
    if max_len is not None and len(v) > max_len:
        raise invalid("Field '%s' is too long" % key)
    return v


def opt_str(b, key, default=None, min_len=0, max_len=None):
    if not has(b, key):
        return default
    return req_str(b, key, min_len=min_len, max_len=max_len)


def req_int(b, key, minimum=None, maximum=None):
    if not has(b, key):
        _missing(key)
    v = b[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid("Field '%s' must be an integer" % key)
    if minimum is not None and v < minimum:
        raise invalid("Field '%s' is below its minimum" % key)
    if maximum is not None and v > maximum:
        raise invalid("Field '%s' is above its maximum" % key)
    return v


def opt_int(b, key, default=None, minimum=None, maximum=None):
    if not has(b, key):
        return default
    return req_int(b, key, minimum=minimum, maximum=maximum)


def req_num(b, key, minimum=None, maximum=None, exclusive_min=None):
    if not has(b, key):
        _missing(key)
    v = b[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid("Field '%s' must be a number" % key)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        raise invalid("Field '%s' must be a finite number" % key)
    if minimum is not None and v < minimum:
        raise invalid("Field '%s' is below its minimum" % key)
    if exclusive_min is not None and v <= exclusive_min:
        raise invalid("Field '%s' must be greater than %s" % (key, exclusive_min))
    if maximum is not None and v > maximum:
        raise invalid("Field '%s' is above its maximum" % key)
    return v


def opt_num(b, key, default=None, minimum=None, maximum=None, exclusive_min=None):
    if not has(b, key):
        return default
    return req_num(b, key, minimum=minimum, maximum=maximum, exclusive_min=exclusive_min)


def req_bool(b, key):
    if not has(b, key):
        _missing(key)
    v = b[key]
    if not isinstance(v, bool):
        raise invalid("Field '%s' must be a boolean" % key)
    return v


def opt_bool(b, key, default=None):
    if not has(b, key):
        return default
    return req_bool(b, key)


def req_enum(b, key, allowed):
    v = req_str(b, key)
    if v not in allowed:
        raise invalid("Field '%s' is not a recognised value" % key)
    return v


def opt_enum(b, key, allowed, default=None):
    if not has(b, key):
        return default
    return req_enum(b, key, allowed)


def req_str_array(b, key):
    if not has(b, key):
        _missing(key)
    v = b[key]
    if not isinstance(v, list):
        raise invalid("Field '%s' must be an array" % key)
    for item in v:
        if not isinstance(item, str):
            raise invalid("Field '%s' must contain only strings" % key)
    return list(v)


def opt_str_array(b, key, default=None):
    if not has(b, key):
        return list(default) if default is not None else None
    return req_str_array(b, key)


def parse_dt(value, key="timestamp"):
    if not isinstance(value, str):
        raise invalid("Field '%s' must be an ISO 8601 timestamp" % key)
    m = _DT_RE.match(value.strip())
    if not m:
        raise invalid("Field '%s' must be an ISO 8601 timestamp" % key)
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=timezone.utc)
    except ValueError:
        raise invalid("Field '%s' is not a valid instant" % key)
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        raw = offset[1:].replace(":", "")
        delta = timedelta(hours=int(raw[:2]), minutes=int(raw[2:4]))
        dt = dt - sign * delta
    return dt


def req_dt(b, key):
    if not has(b, key):
        _missing(key)
    return parse_dt(b[key], key)


def opt_dt(b, key, default=None):
    if not has(b, key):
        return default
    return parse_dt(b[key], key)


def req_date(b, key):
    v = req_str(b, key)
    m = _DATE_RE.match(v)
    if not m:
        raise invalid("Field '%s' must be a YYYY-MM-DD date" % key)
    try:
        datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
    except ValueError:
        raise invalid("Field '%s' must be a valid calendar date" % key)
    return v


def date_at(date_str, hour, day_offset=0):
    m = _DATE_RE.match(date_str)
    base = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
    return base + timedelta(days=day_offset, hours=hour)


# --------------------------------------------------------------------------- #
# query-string helpers
# --------------------------------------------------------------------------- #
def q_str(key):
    v = request.args.get(key)
    if v is None:
        return None
    return v


def q_enum(key, allowed):
    v = request.args.get(key)
    if v is None:
        return None
    if v not in allowed:
        raise invalid("Query parameter '%s' is not a recognised value" % key)
    return v


def q_int(key, minimum=None, maximum=None):
    v = request.args.get(key)
    if v is None:
        return None
    try:
        parsed = int(v)
    except (TypeError, ValueError):
        raise invalid("Query parameter '%s' must be an integer" % key)
    if minimum is not None and parsed < minimum:
        raise invalid("Query parameter '%s' is below its minimum" % key)
    if maximum is not None and parsed > maximum:
        raise invalid("Query parameter '%s' is above its maximum" % key)
    return parsed


def q_bool(key):
    v = request.args.get(key)
    if v is None:
        return None
    low = v.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise invalid("Query parameter '%s' must be a boolean" % key)


def pagination():
    """PRD §2.3 — limit defaults to 10 (1..100), offset defaults to 0."""
    limit = q_int("limit", minimum=1, maximum=100)
    offset = q_int("offset", minimum=0)
    return (10 if limit is None else limit), (0 if offset is None else offset)


def page(items, limit, offset):
    total = len(items)
    window = items[offset:offset + limit]
    return window, total
