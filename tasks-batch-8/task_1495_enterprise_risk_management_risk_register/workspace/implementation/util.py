"""Shared helpers: time formatting/parsing, body validation, pagination."""
import math
import random
import string
from datetime import datetime, timezone
from decimal import Decimal

from flask import request

from errors import ApiError


def band_of(score):
    """PRD 2.6: 1-4 LOW, 5-9 MEDIUM, 10-15 HIGH, 16-25 CRITICAL."""
    if score <= 4:
        return "LOW"
    if score <= 9:
        return "MEDIUM"
    if score <= 15:
        return "HIGH"
    return "CRITICAL"


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be an ISO8601 datetime string" % field)
    t = value.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' is not a valid ISO8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def _present(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field '%s'" % field)
    return data[field]


def req_str(data, field):
    v = _present(data, field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a string" % field)
    return v


def opt_str(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a string" % field)
    return v


def opt_bool(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a boolean" % field)
    return v


def req_int(data, field):
    v = _present(data, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be an integer" % field)
    return v


def opt_int(data, field):
    v = data.get(field)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be an integer" % field)
    return v


def _to_decimal(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a number" % field)
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s' must be a finite number" % field)
    return Decimal(str(v))


def req_num(data, field):
    return _to_decimal(_present(data, field), field)


def opt_num(data, field):
    v = data.get(field)
    if v is None:
        return None
    return _to_decimal(v, field)


def req_dt(data, field):
    return parse_dt(_present(data, field), field)


def req_enum(data, field, allowed):
    v = req_str(data, field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Field '%s' must be one of %s" % (field, ", ".join(allowed)))
    return v


def paginate(items):
    """PRD 2.3: limit default 10, min 1, max 100; offset default 0."""
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid pagination parameters")
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid pagination parameters")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
