"""Time, decimal, pagination, and request-body helpers."""

import calendar
import math
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from flask import request

from errors import ApiError, ERR_REFERENTIAL_INTEGRITY


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime (or bare date, taken as 00:00Z) to aware UTC."""
    if isinstance(value, str):
        s = value.strip()
        try:
            if len(s) == 10 and s[4] == "-" and s[7] == "-":
                s = s + "T00:00:00+00:00"
            elif s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        except ValueError:
            raise ApiError(
                ERR_REFERENTIAL_INTEGRITY, 422,
                "Field '%s' is not a valid ISO 8601 datetime" % field,
            )
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise ApiError(
        ERR_REFERENTIAL_INTEGRITY, 422,
        "Field '%s' must be an ISO 8601 datetime string" % field,
    )


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_12_months(dt):
    year = dt.year + 1
    month = dt.month
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def days_in_month(year, month):
    return calendar.monthrange(year, month)[1]


# ---------------------------------------------------------------------------
# Decimal / rounding discipline
# ---------------------------------------------------------------------------

def round_half_up_cents(value):
    """Round a Decimal to whole cents, half up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_decimal(value):
    """Exact Decimal from a JSON number (int/float) without float artifacts."""
    if isinstance(value, bool):
        raise ValueError("not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, Decimal):
        return value
    raise ValueError("not a number")


# ---------------------------------------------------------------------------
# Request body / field helpers
# ---------------------------------------------------------------------------

def get_body():
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def need(body, name):
    value = body.get(name)
    if value is None:
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422, "Field '%s' is required" % name
        )
    return value


def need_str(body, name):
    value = need(body, name)
    if not isinstance(value, str):
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422, "Field '%s' must be a string" % name
        )
    return value


def need_int(body, name):
    value = need(body, name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422, "Field '%s' must be an integer" % name
        )
    return value


def need_number(body, name):
    value = need(body, name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422, "Field '%s' must be a number" % name
        )
    return value


def need_dt(body, name):
    return parse_dt(need(body, name), field=name)


def opt_bool(body, name, default=False):
    value = body.get(name, default)
    if not isinstance(value, bool):
        raise ApiError(
            ERR_REFERENTIAL_INTEGRITY, 422, "Field '%s' must be a boolean" % name
        )
    return value


# ---------------------------------------------------------------------------
# Pagination (limit/offset; defaults 10/0; limit clamped to [1, 100])
# ---------------------------------------------------------------------------

def paginate(items):
    """items: full sorted list. Returns (page_items, pagination_meta)."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


def sort_items(items):
    """Default list ordering: created_at ascending, insertion order as tiebreak."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def ceil_div_to_int(numer, denom):
    """ceil(numer/denom) for non-negative ints."""
    return -(-numer // denom)


def ceil_minutes(delta):
    """ceil of a timedelta expressed in minutes (exact, microsecond-based)."""
    micros = (delta.days * 86400 + delta.seconds) * 1000000 + delta.microseconds
    return ceil_div_to_int(micros, 60 * 1000000)


def ceil_distance_km(distance_km):
    """ceil of the raw distance value (Decimal-exact for JSON floats)."""
    return math.ceil(to_decimal(distance_km))
