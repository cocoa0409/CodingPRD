"""Shared helpers: ids, timestamps, logical clock, Decimal money math.

Timestamp conventions (pinned by PRD and design docs):
- created_at / updated_at / api_request_timestamp: ISO 8601 UTC, three
  fractional digits (PRD 2.2 / 2.4) — wall clock, since they are not
  deadline/window/expiry checks.
- Every business instant (submitted_at, verified_at, issued_at, expires_at,
  notice_sent_at, appeal_deadline_at, ...) reads the logical clock and is
  emitted at second precision, e.g. "2026-08-31T00:00:00Z".
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """ISO 8601 UTC timestamp with three fractional digits (wall clock)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5): starts at 2026-08-01T00:00:00Z; the only way time
# moves is POST /api/_clock/set_current_utc; never falls back to wall clock.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s: str) -> datetime:
    """Parse an ISO-8601 instant; naive values are read as UTC."""
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
    """Logical-clock instant at second precision: 2026-08-31T00:00:00Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LogicalClock:
    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK).replace(microsecond=0)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_dt(self._dt)

    def set(self, to_iso8601: str) -> datetime:
        # PRD: moves the logical clock to the supplied instant (arbitrary).
        self._dt = parse_dt(to_iso8601).replace(microsecond=0)
        return self._dt


CLOCK = LogicalClock()


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=int(days))


# ---------------------------------------------------------------------------
# Money / rate math — Decimal everywhere; round half up unless pinned to floor.
# ---------------------------------------------------------------------------

def dec(value) -> Decimal:
    """Exact Decimal from a JSON number (str() of float/int is shortest-repr)."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up_cents(x: Decimal) -> int:
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_cents(x: Decimal) -> int:
    return int(x.to_integral_value(rounding=ROUND_FLOOR))
