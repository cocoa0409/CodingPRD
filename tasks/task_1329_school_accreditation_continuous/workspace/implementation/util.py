"""Parsing, validation, rounding, date-math, and pagination helpers."""
import calendar
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import wall_now_iso
from errors import ApiError


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string into an aware datetime (UTC assumed)."""
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be an ISO 8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def add_years(dt, years):
    """Calendar-year addition; Feb 29 clamps to Feb 28 in non-leap years."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 in non-leap target year
        return dt.replace(year=dt.year + years, month=2, day=28)


def add_months(dt, months):
    """Calendar-month addition preserving day-of-month; clamps to last day."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    last_day = calendar.monthrange(y, m)[1]
    d = min(dt.day, last_day)
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------

def round_half_up_2(value):
    """Round a Decimal to exactly 2 decimal places, half-up. Returns float."""
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# Request body / field validation (ERR_VALIDATION, HTTP 400)
# ---------------------------------------------------------------------------

def body():
    """Return the JSON request body as a dict ({} when absent)."""
    if request.data:
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError("ERR_VALIDATION", 400, "Request body must be valid JSON")
        if not isinstance(data, dict):
            raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
        return data
    return {}


def required(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {field}")
    return data[field]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def as_int(v, field):
    if not _is_int(v):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    return v


def as_str(v, field):
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a string")
    return v


def as_num(v, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a number")
    return v


def as_enum(v, field, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(
            "ERR_VALIDATION",
            400,
            f"Field {field} must be one of {sorted(allowed)}",
        )
    return v


# ---------------------------------------------------------------------------
# Pagination (scaffold pagination_fields: limit / offset / total_count / has_more)
# ---------------------------------------------------------------------------

def pagination():
    """Parse limit/offset query params per scaffold defaults: limit=10, min 1, max 100, offset=0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Slice items (already sorted by created_at ASC) and return (page, total)."""
    total = len(items)
    return items[offset: offset + limit], total


# ---------------------------------------------------------------------------
# Entity record helpers
# ---------------------------------------------------------------------------

def stamp_new(record, with_version=True):
    """Populate id/created_at/updated_at/version on a fresh record dict."""
    record["created_at"] = wall_now_iso()
    if with_version:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and increment version by exactly 1."""
    record["updated_at"] = wall_now_iso()
    record["version"] += 1
    return record
