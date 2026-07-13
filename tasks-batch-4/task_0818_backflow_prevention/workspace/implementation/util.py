"""Datetime parsing/formatting, response envelope, error type, id/meta helpers."""

import math
import random
import string
import calendar
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta

import store


# ===========================================================================
# Errors
# ===========================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ===========================================================================
# Datetime helpers
# ===========================================================================
def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Returns None for
    None. Raises ValueError on malformed input."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s == "":
            raise ValueError("empty datetime")
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # date-only fallback
            dt = datetime.fromisoformat(s + "T00:00:00")
    else:
        raise ValueError("invalid datetime type")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime to ISO-8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_months(base, n):
    """Add n whole calendar months, preserving day-of-month (clamped to the
    last day of the target month) and copying the time-of-day."""
    y, m, d = base.year, base.month, base.day
    total = (m - 1) + n
    ny = y + total // 12
    nm = total % 12 + 1
    nd = min(d, calendar.monthrange(ny, nm)[1])
    return base.replace(year=ny, month=nm, day=nd)


def whole_days_between(later, earlier):
    """floor((later - earlier)/1 day) as a signed whole-day count."""
    delta = later - earlier
    return math.floor(delta.total_seconds() / 86400.0)


# ===========================================================================
# Decimal / rounding helpers
# ===========================================================================
def round_half_up_cents(dec_value):
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(dec_value):
    return dec_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ===========================================================================
# Response envelope
# ===========================================================================
def _request_id():
    rnd = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + rnd


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(store.wall_now()),
    }
    if extra:
        m.update(extra)
    return m


def serialize(entity):
    """Copy an entity dict to a JSON-safe dict, formatting datetimes and
    dropping internal underscore-prefixed keys."""
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if isinstance(data, dict) else serialize(data),
    }
    return body, status


def array_response(items, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return body, 200


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return body, err.http_status


# ===========================================================================
# Pagination
# ===========================================================================
def paginate(args):
    """Read limit/offset from query args, validating ranges (limit 1..100,
    default 10; offset >=0 default 0)."""
    limit = args.get("limit")
    offset = args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 400, "limit out of range")
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset out of range")
    return limit, offset


def apply_list(rows, limit, offset):
    """Sort by creation order and window. rows: list of entity dicts."""
    ordered = sorted(rows, key=lambda r: r["_seq"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return [serialize(r) for r in window], total
