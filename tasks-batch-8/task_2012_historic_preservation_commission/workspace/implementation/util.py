"""Shared helpers: ids, timestamps, logical clock, money rounding.

Timestamps come in two flavors (PRD 2.4 vs 2.5):
- created_at / updated_at / api_request_timestamp: wall-clock ISO 8601 UTC with
  three fractional digits.
- Every business timestamp (decided_at, returned_at, adopted_at, issued_at,
  delay ends, ...) is stamped from the logical clock, never wall-clock time.
Logical-clock timestamps round-trip at the precision they were set with:
second-precision instants render as ...T00:00:00Z, millisecond instants render
with three fractional digits, and finer inputs keep six.
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone

from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 instant, normalize to UTC, keep full precision."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt: datetime) -> str:
    """Canonical UTC rendering; round-trips the precision the clock was set with."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if dt.microsecond % 1000 == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class LogicalClock:
    """Server logical clock. Starts at the fixed default and never falls back
    to wall-clock time once set."""

    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_dt(self._dt)

    def set(self, to_iso8601) -> datetime:
        if isinstance(to_iso8601, datetime):
            self._dt = to_iso8601.astimezone(timezone.utc)
        else:
            self._dt = parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def whole_days_between(start: datetime, end: datetime) -> int:
    """floor((end - start) / 86400) — whole days elapsed from start to end."""
    delta = end - start
    return int(delta.total_seconds() // 86400)


# ---------------------------------------------------------------------------
# Money: integer cents with pinned round-half-up (PRD 2.6)
# ---------------------------------------------------------------------------

def round_half_up_cents(value: Decimal) -> int:
    """Round a Decimal amount to integer cents, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate_times_cents(rate: str, cents: int) -> int:
    """round_half_up(rate * cents) computed exactly (rate given as a decimal string)."""
    return round_half_up_cents(Decimal(rate) * Decimal(int(cents)))
