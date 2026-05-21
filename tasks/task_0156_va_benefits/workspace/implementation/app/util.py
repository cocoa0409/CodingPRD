"""Common helpers: rounding, decimals, pagination, UUIDs."""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any, Iterable

from .errors import ApiError


def new_id() -> str:
    return str(uuid.uuid4())


def round_half_up(value: Decimal | float | int | str, places: int) -> Decimal:
    """Round half-up to `places` decimal places, return Decimal."""
    d = Decimal(str(value))
    q = Decimal(1).scaleb(-places)  # 10^(-places)
    return d.quantize(q, rounding=ROUND_HALF_UP)


def floor_to_cent(value: Decimal | float | int | str) -> Decimal:
    d = Decimal(str(value))
    return d.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def money(value: Decimal | float | int | str) -> Decimal:
    """Coerce to two-decimal Decimal (half-up). Used for storage round-trip."""
    return round_half_up(value, 2)


def to_float(value: Decimal | float | int | None) -> float | int | None:
    """Convert Decimal to a JSON-friendly float (two-decimal money) or int."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        # round to 2dp for money, keep stable repr
        return float(value)
    return value


# ---------- Pagination ----------

def parse_pagination(args: Any) -> tuple[int, int]:
    """Read `limit` and `offset` from the Flask request args.

    Defaults: limit=10 (min 1, max 100); offset=0 (>=0). Reject invalid values
    with ERR_INVALID_BODY (422) — the spec uses the general validation rule.
    """
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    limit = 10
    offset = 0

    if limit_raw is not None and str(limit_raw) != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_BODY", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_BODY", "limit must be between 1 and 100")

    if offset_raw is not None and str(offset_raw) != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_BODY", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_BODY", "offset must be >= 0")

    return limit, offset


def paginate(items: Iterable[Any], limit: int, offset: int) -> tuple[list[Any], int]:
    items_list = list(items)
    total = len(items_list)
    return items_list[offset : offset + limit], total


# ---------- UTC date helpers ----------

UTC = timezone.utc


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def utc_date_floor(dt: datetime) -> datetime:
    """Floor a datetime to the UTC day start (00:00:00.000)."""
    d = to_utc(dt)
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def days_between(start: datetime, end: datetime) -> int:
    """Whole UTC days between start (inclusive) and end (exclusive).

    Negative if end < start; the caller is responsible for clamping.
    """
    s = to_utc(start)
    e = to_utc(end)
    delta = e - s
    return int(math.floor(delta.total_seconds() / 86400.0))


def days_in_month(year: int, month: int) -> int:
    """Number of days in a calendar month."""
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=UTC)
    cur = datetime(year, month, 1, tzinfo=UTC)
    return (nxt - cur).days


def month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    """Return [start, end) of a calendar month in UTC."""
    start = datetime(year, month, 1, tzinfo=UTC)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, month + 1, 1, tzinfo=UTC)
    return start, end
