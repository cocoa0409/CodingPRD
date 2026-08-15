"""Shared helpers: timestamps, rounding, calendar math, response envelope,
and request-shape validation (validation pipeline steps 1-3)."""

import math
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, localcontext

from flask import jsonify

from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_ENUM

SECONDS_PER_DAY = 86400


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_iso():
    """Wall-clock timestamp for the meta envelope."""
    return iso(datetime.now(timezone.utc))


def parse_dt(value):
    """Parse an ISO 8601 string to an aware UTC datetime; None if unparseable."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_calendar_months(dt, months):
    """Add whole calendar months, clamping the day to the target month's last
    day (2026-01-31 + 6mo = 2026-07-31; 2025-08-31 + 6mo = 2026-02-28)."""
    total = dt.year * 12 + (dt.month - 1) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    if month == 12:
        next_first = datetime(year + 1, 1, 1)
    else:
        next_first = datetime(year, month + 1, 1)
    last_day = (next_first - timedelta(days=1)).day
    return dt.replace(year=year, month=month, day=min(dt.day, last_day))


def floor_days(delta):
    """Whole days of 86400 seconds, rounded down (floor)."""
    return math.floor(delta.total_seconds() / SECONDS_PER_DAY)


def year_bounds(dt):
    """[Jan 1 00:00:00 inclusive, next Jan 1 00:00:00 exclusive) in UTC."""
    start = datetime(dt.year, 1, 1, tzinfo=timezone.utc)
    end = datetime(dt.year + 1, 1, 1, tzinfo=timezone.utc)
    return start, end


# ---------------------------------------------------------------------------
# Money / rounding
# ---------------------------------------------------------------------------

def round_half_up_cents(numerator, denominator=1):
    """Round numerator/denominator half-up to whole cents (integer)."""
    with localcontext() as ctx:
        ctx.prec = 40
        q = (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def round_half_up_decimal(value, places=6):
    """Round a Decimal half-up to the given number of decimal places."""
    with localcontext() as ctx:
        ctx.prec = 40
        q = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return q


def dec_pow_half(exponent):
    """0.5 ** exponent with Decimal precision (exponent is a Decimal)."""
    with localcontext() as ctx:
        ctx.prec = 40
        return Decimal("0.5") ** exponent


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------

def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def respond_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": wall_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def respond_list(items, total_count, limit, offset, status=200):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": wall_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def respond_error(error_id, status, message):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": wall_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------

def parse_pagination(args):
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if isinstance(raw_limit, str) and not raw_limit.strip().lstrip("-").isdigit():
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if isinstance(raw_offset, str) and not raw_offset.strip().lstrip("-").isdigit():
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items: full sorted list. Returns (page, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Request-shape validation (pipeline steps 2 and 3)
# ---------------------------------------------------------------------------

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid required field: %s" % name)
    return v


def opt_str(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s must be a string" % name)
    return v


def req_int(body, name):
    v = body.get(name)
    if not is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or invalid required field: %s" % name)
    return v


def opt_int(body, name, default=None):
    v = body.get(name, default)
    if v is not None and not is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s must be an integer" % name)
    return v


def opt_bool(body, name, default=False):
    v = body.get(name, default)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field %s must be a boolean" % name)
    return v


def req_dt(body, name):
    v = body.get(name)
    dt = parse_dt(v)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing or unparseable datetime field: %s" % name)
    return dt


def opt_dt(body, name, default=None):
    if name not in body or body.get(name) is None:
        return default
    dt = parse_dt(body.get(name))
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Unparseable datetime field: %s" % name)
    return dt


def check_enum(value, members, field_name):
    """Pipeline step 3: enum membership (value must be a declared member)."""
    if not isinstance(value, str) or value not in members:
        raise ApiError(ERR_INVALID_ENUM, 400,
                       "Field %s must be one of %s" % (field_name, ", ".join(members)))
    return value
