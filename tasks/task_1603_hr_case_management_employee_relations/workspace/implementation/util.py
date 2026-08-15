"""Shared helpers: ids, logical clock, timestamp formats, business-day calendar arithmetic.

Timestamp policy (PRD §2.2/§2.4):
  - common fields (created_at, updated_at) and the envelope's api_request_timestamp
    are ISO 8601 UTC with three fractional digits (e.g. 2026-08-01T09:15:00.000Z);
  - server-stamped domain instants (intake_received_at, sla_due_date, closed_at,
    completed_at, sent_at, sealed_at, as_of) and input-echoed datetimes
    (hire_date, scheduled_start/end, holiday_date) are rendered at second
    precision (e.g. 2026-08-18T17:00:00Z).
"""
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5). Starts at exactly 2026-08-01T00:00:00Z on boot.
# The clock is freely settable — forward or backward — by ERManager.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s):
    """Parse an ISO 8601 datetime/date string to an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if not t:
        raise ValueError("empty")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt: datetime) -> str:
    """Second-precision UTC rendering."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_dt_ms(dt: datetime) -> str:
    """Millisecond-precision UTC rendering (three fractional digits)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def set(self, to_iso8601: str) -> datetime:
        self._dt = parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


# ---------------------------------------------------------------------------
# Business-day arithmetic (PRD §2.5, §3.2)
# ---------------------------------------------------------------------------

def is_business_day(d: date, holidays: set) -> bool:
    return d.weekday() < 5 and d not in holidays


def compute_sla_due_date(intake_dt: datetime, business_days: int, holidays: set) -> datetime:
    """Intake day is day 0 and never counts; advance day-by-day skipping
    Saturdays, Sundays, and holidays until the allowance reaches zero; the
    resulting day is stamped at exactly 17:00:00 UTC."""
    cursor = intake_dt.date()
    remaining = business_days
    while True:
        cursor += timedelta(days=1)
        if not is_business_day(cursor, holidays):
            continue
        remaining -= 1
        if remaining == 0:
            return datetime(cursor.year, cursor.month, cursor.day, 17, 0, 0,
                            tzinfo=timezone.utc)


def compute_overdue_business_days(now_dt: datetime, due_dt: datetime, holidays: set) -> int:
    """Zero while now <= sla_due_date; otherwise the count of business days in
    the half-open interval (date(sla_due_date), date(now)] — the first business
    day after the due date counts as one."""
    if now_dt <= due_dt:
        return 0
    cursor = due_dt.date()
    end = now_dt.date()
    count = 0
    while cursor < end:
        cursor += timedelta(days=1)
        if is_business_day(cursor, holidays):
            count += 1
    return count


def quarter_start(dt: datetime) -> datetime:
    m = 3 * ((dt.month - 1) // 3) + 1
    return datetime(dt.year, m, 1, tzinfo=timezone.utc)


def quarter_end_date(dt: datetime) -> date:
    qs = quarter_start(dt)
    end_month = qs.month + 2
    end_year = qs.year
    if end_month > 12:
        end_month -= 12
        end_year += 1
    # last day of end_month
    if end_month == 12:
        nxt = date(end_year + 1, 1, 1)
    else:
        nxt = date(end_year, end_month + 1, 1)
    return nxt - timedelta(days=1)
