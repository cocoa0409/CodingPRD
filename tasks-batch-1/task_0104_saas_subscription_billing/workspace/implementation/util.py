"""Shared helpers: datetime parsing, money rounding, pagination."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors

CYCLE_DAYS = 30
RECOGNITION_DAYS = 30
DUNNING_MAX_ATTEMPTS = 3
DUNNING_RETRY_OFFSETS_DAYS = [0, 3, 7]
MIN_PAUSE_GAP_DAYS = 7
TAX_BPS_DENOMINATOR = 10000


# ---- datetime ---------------------------------------------------------------
def parse_dt(value):
    """Parse an ISO 8601 UTC string into an aware UTC datetime.

    Raises ERR_INVALID_REQUEST when not a parseable timestamp.
    """
    if not isinstance(value, str) or value.strip() == "":
        raise errors.invalid_request("Expected an ISO 8601 UTC timestamp string")
    s = value.strip()
    # Accept trailing Z (UTC).
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request(f"Malformed timestamp: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Render an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days(dt, days):
    return dt + timedelta(days=days)


def floor_days(later, earlier):
    """Full days between two datetimes (floor of the difference in days)."""
    delta = later - earlier
    return delta.days if delta.days >= 0 else -((-delta).days + (1 if (-delta).seconds or (-delta).microseconds else 0))


def full_days_elapsed(now, start):
    """Full days consumed = floor((now - start) / 1 day). Non-negative inputs
    expected; returns an int that floors toward zero of the day component."""
    delta = now - start
    total_seconds = delta.total_seconds()
    return int(total_seconds // 86400)


# ---- money ------------------------------------------------------------------
def round_half_up(numerator, denominator):
    """round_half_up(numerator/denominator) -> int cents.

    Uses Decimal so a fractional remainder of exactly one-half rounds upward
    (PRD §2.5). numerator/denominator are integers.
    """
    q = (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


# ---- pagination -------------------------------------------------------------
def parse_pagination():
    """Read limit/offset query params with PRD §2.3 defaults & range checks.

    Returns (limit, offset). Raises ERR_VALIDATION_RANGE on out-of-bounds.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.validation_range("limit must be an integer in 1..100")
        if limit < 1 or limit > 100:
            raise errors.validation_range("limit must be within 1..100")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.validation_range("offset must be a non-negative integer")
        if offset < 0:
            raise errors.validation_range("offset must be >= 0")

    return limit, offset


def paginate(items, limit, offset):
    """Slice a list (already sorted by created_at asc) and build pagination meta."""
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


def sort_by_created(items):
    """List endpoints sort by created_at ascending (PRD §2.3)."""
    return sorted(items, key=lambda o: (o["created_at"], o["id"]))
