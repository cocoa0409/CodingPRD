"""Shared helpers: input parsing, pagination, datetime math, rounding."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import iso
from errors import err


# ---------------------------------------------------------------------------
# Datetime parsing / month arithmetic
# ---------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime.

    Accepts trailing 'Z' or explicit offset. Raises ERR_INVALID_REQUEST on failure.
    """
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", "Invalid datetime")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "Invalid ISO 8601 datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Add a whole number of calendar months to a datetime (clamping day-of-month).

    Used for paid_through (+1 month), commitment window (+N months), and the
    refund cycle start (-1 month, via months negative).
    """
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day to the last valid day of the target month
    day = dt.day
    # find last day of target month
    if month == 12:
        next_month_first = datetime(year + 1, 1, 1, tzinfo=dt.tzinfo)
    else:
        next_month_first = datetime(year, month + 1, 1, tzinfo=dt.tzinfo)
    last_day = (next_month_first - timedelta(days=1)).day
    if day > last_day:
        day = last_day
    return dt.replace(year=year, month=month, day=day)


def days_in_interval(start, end):
    """Calendar days between two instants as a whole-number count.

    PRD 3.7: 'the count of calendar days in that interval'. Negative clamped to 0.
    """
    delta = end - start
    days = delta.total_seconds() / 86400.0
    if days < 0:
        return 0
    # whole days
    return int(days)


def round_half_up(numerator, denominator):
    """round_half_up(numerator/denominator) -> integer (PRD 2.7)."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def round_half_up_frac(amount, fraction):
    """round_half_up(amount * fraction) -> integer cents."""
    q = (Decimal(amount) * Decimal(str(fraction))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


# ---------------------------------------------------------------------------
# Body / query parsing
# ---------------------------------------------------------------------------
def get_json_body():
    """Return the parsed JSON body as a dict (empty dict when none)."""
    if request.data and len(request.data) > 0:
        data = request.get_json(silent=True)
        if data is None:
            raise err("ERR_INVALID_REQUEST", "Malformed JSON body")
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "Body must be a JSON object")
        return data
    return {}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % f)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", "Invalid %s; must be one of %s" % (field, sorted(allowed)))


def require_nonneg_int(value, field):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise err("ERR_INVALID_REQUEST", "%s must be a non-negative integer" % field)
    return value


def require_int_in_range(value, lo, hi, field):
    if not isinstance(value, int) or isinstance(value, bool) or value < lo or value > hi:
        raise err("ERR_INVALID_REQUEST", "%s must be an integer in [%d, %d]" % (field, lo, hi))
    return value


def require_bool(value, field):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", "%s must be a boolean" % field)
    return value


def require_str(value, field):
    if not isinstance(value, str) or value == "":
        raise err("ERR_INVALID_REQUEST", "%s must be a non-empty string" % field)
    return value


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    """Return (limit, offset). limit default 10, range [1,100]; offset default 0."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be in [1, 100]")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Return the page slice; caller passes total_count = len(items)."""
    return items[offset:offset + limit]


def sort_by_created(items):
    """Default list sort: created_at ascending, with seq as a stable tiebreaker."""
    return sorted(items, key=lambda r: (r["created_at_dt"], r.get("_seq", 0)))
