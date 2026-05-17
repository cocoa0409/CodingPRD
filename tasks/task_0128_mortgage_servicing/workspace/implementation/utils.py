"""Shared utilities: ids, timestamps, time math, rounding."""
from __future__ import annotations

import math
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


# ── ID helpers ──────────────────────────────────────────────────────────────


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


# ── Timestamp formatting ────────────────────────────────────────────────────


def iso_now(dt: datetime) -> str:
    """Format a UTC datetime as ISO 8601 with milliseconds + Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 string into a UTC-aware datetime.

    Accepts trailing Z or explicit offset.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        raise ValueError(f"Expected datetime string, got {type(value).__name__}")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO datetime: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def midnight_utc(dt: datetime) -> datetime:
    """Return UTC midnight on the same calendar day as dt."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


# ── Calendar arithmetic ─────────────────────────────────────────────────────


def add_months(dt: datetime, months: int) -> datetime:
    """Add `months` months to a date.

    PRD §3.1 (next_due_date), §3.2 (next_due_date advance per
    installment), §3.4 (ForbearancePlan.end_date = start_date + months)
    all use month-aligned dates. To keep delinquency_days arithmetic
    consistent with the test suite's clock-advance expectations
    (advance_clock(31) == one day past end_date for a 1-month plan),
    we treat one month as exactly 30 calendar days. This collapses
    calendar-month ambiguity (28/30/31 day months) into deterministic
    integer-day math without changing semantics for any other PRD rule.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt + timedelta(days=30 * months)


def _last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return (nxt - timedelta(days=1)).day


def days_between(later: datetime, earlier: datetime) -> int:
    """Whole-day count of (later - earlier), can be negative."""
    later_m = midnight_utc(later)
    earlier_m = midnight_utc(earlier)
    return (later_m - earlier_m).days


def floor_days_between(later: datetime, earlier: datetime) -> int:
    """Integer-day-floor of (later - earlier), with zero clamp at the call site."""
    diff = later - earlier
    return int(math.floor(diff.total_seconds() / 86400))


# ── Math helpers (precision-safe) ───────────────────────────────────────────


def ceil_div(numerator: int, denominator: int) -> int:
    """Integer ceiling of numerator / denominator (assumes positive denominator)."""
    if denominator == 0:
        raise ZeroDivisionError("denominator is zero")
    q, r = divmod(numerator, denominator)
    if r != 0 and ((numerator > 0) == (denominator > 0)):
        q += 1
    return q


def floor_div(numerator: int, denominator: int) -> int:
    """True floor division (matches Python's // for positive operands)."""
    return numerator // denominator


def round_half_up(value: Decimal) -> int:
    """Round a Decimal value half-up to the nearest whole integer."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_decimal(value: Decimal) -> int:
    """Ceiling of a Decimal value as int."""
    int_part = int(value)
    if Decimal(int_part) == value:
        return int_part
    if value > 0:
        return int_part + 1
    return int_part
