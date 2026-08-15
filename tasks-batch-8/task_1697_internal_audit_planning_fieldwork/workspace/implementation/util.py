"""Shared helpers: ids, timestamps, the logical clock, calendar and Decimal math."""
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """Wall-clock ISO 8601 UTC timestamp with three fractional digits.

    Used for created_at/updated_at/api_request_timestamp (PRD 2.2/2.4). Business
    timestamps (submitted_at, issued_at, ...) come from the logical clock instead.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 datetime (Z or offset); naive values are read as UTC."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_clock(dt: datetime) -> str:
    """Logical-clock timestamp format: second precision, Z suffix."""
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


class LogicalClock:
    """The logical clock (PRD 2.5). Starts at exactly 2026-08-01T00:00:00Z and
    never falls back to wall-clock time. AuditAdmin may move it to any instant."""

    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return fmt_clock(self._dt)

    def today(self) -> date:
        return self._dt.date()

    def set(self, to_iso8601: str) -> datetime:
        self._dt = parse_dt(to_iso8601).replace(microsecond=0)
        return self._dt


CLOCK = LogicalClock()


# ---------------------------------------------------------------------------
# Calendar and numeric helpers
# ---------------------------------------------------------------------------

def full_months_between(d1: date, d2: date) -> int:
    """Whole calendar months: (y2-y1)*12 + (m2-m1) - (1 if day2 < day1 else 0)."""
    return (d2.year - d1.year) * 12 + (d2.month - d1.month) - (1 if d2.day < d1.day else 0)


def dec(x) -> Decimal:
    """Exact Decimal from an int/float/str JSON number (avoids binary float noise)."""
    return Decimal(str(x))


def item_hours(hours_worked) -> Decimal:
    """Per-item half-hour ceiling: ceil(hours*2)/2 (PRD 3.5 pinned rounding)."""
    return (dec(hours_worked) * 2).to_integral_value(rounding=ROUND_CEILING) / Decimal(2)


def round2(value: Decimal) -> float:
    """round_half_up to exactly two decimal places, returned as a float."""
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def days_overdue(due_date_str: str, clock: LogicalClock) -> int:
    """Whole-day overdue count: max(0, (clock_date - due_date).days) at date
    granularity (PRD calculations.action_plan_overdue_days)."""
    due = parse_dt(due_date_str).date()
    return max(0, (clock.today() - due).days)


def days_shift(from_date_str: str, to_date_str: str) -> int:
    """Whole days between two datetimes (extension approved_days)."""
    return (parse_dt(to_date_str) - parse_dt(from_date_str)).days
