"""Shared helpers: datetime parsing/formatting, Decimal math, validation, pagination."""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

from errors import fail


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime (or date-only) string into an aware UTC datetime.

    Returns None when the value is not a parseable datetime string.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        iso = s
        if iso.endswith(("Z", "z")):
            iso = iso[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def require_dt(value, field):
    dt = parse_dt(value)
    if dt is None:
        fail("ERR_INVALID_REQUEST", f"Field '{field}' must be an ISO 8601 datetime string")
    return dt


# ---------------------------------------------------------------------------
# Decimal / rounding helpers (PRD 2.7)
# ---------------------------------------------------------------------------

def dec(value):
    """Decimal from an int/float/str without binary float artifacts."""
    return Decimal(str(value))


def round_half_up_cents(value):
    """Round half up to whole cents, returned as int."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_int(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round half up to two decimal places, returned as float for JSON."""
    return float(dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_1dp(value):
    return float(dec(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def floor_cents(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Body validation helpers (priority 4 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def body_json(required=True):
    from flask import request

    data = request.get_json(silent=True)
    if data is None:
        if required:
            fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not v.strip():
        fail("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be a non-empty string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        fail("ERR_INVALID_REQUEST", f"Field '{field}' must be a non-empty string")
    return v


def req_int(body, field, min_value=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be an integer")
    if min_value is not None and v < min_value:
        fail("ERR_INVALID_REQUEST", f"Field '{field}' must be >= {min_value}")
    return v


def req_number(body, field, min_value=None, allow_zero=False):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be a number")
    if min_value is not None:
        if allow_zero:
            if v < min_value:
                fail("ERR_INVALID_REQUEST", f"Field '{field}' must be >= {min_value}")
        elif v <= min_value:
            fail("ERR_INVALID_REQUEST", f"Field '{field}' must be > {min_value}")
    return v


def req_enum(body, field, domain):
    v = body.get(field)
    if v not in domain:
        fail("ERR_INVALID_REQUEST", f"Field '{field}' must be one of {sorted(domain)}")
    return v


def req_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        fail("ERR_INVALID_REQUEST", f"Field '{field}' is required and must be a list")
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10 (min 1, max 100), offset default 0
# ---------------------------------------------------------------------------

def pagination_args():
    from flask import request

    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer")
        if limit < 1:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be >= 1")
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be >= 0")
    return limit, offset
