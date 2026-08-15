"""Date/time helpers, the logical clock, and rounding discipline."""
import re
from datetime import datetime, date, timedelta, timezone
from calendar import monthrange
from decimal import Decimal, ROUND_HALF_UP

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LogicalClock:
    """The server logical clock. Starts at exactly 2026-08-01T00:00:00Z and
    never falls back to wall-clock time. Also hands out strictly increasing
    created_at/updated_at stamps (millisecond granularity) so ledger replay
    order ties can never occur."""

    def __init__(self):
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self._last_stamp = None

    def now(self):
        return self._now

    def date(self):
        return self._now.date()

    def set(self, dt):
        self._now = dt

    def stamp(self):
        cand = self._now
        if self._last_stamp is not None and cand <= self._last_stamp:
            cand = self._last_stamp + timedelta(milliseconds=1)
        self._last_stamp = cand
        return fmt_ts(cand)

    def clock_ts(self):
        """Exact logical-clock timestamp (no monotonic bump)."""
        return fmt_ts(self._now)


CLOCK = LogicalClock()


def fmt_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_date(d):
    return d.isoformat()


def parse_date(s):
    """Strict YYYY-MM-DD parse. Raises ValueError on any defect."""
    if not isinstance(s, str) or not DATE_RE.match(s):
        raise ValueError("not an ISO date")
    return date.fromisoformat(s)


def parse_ts(s):
    """Parse an ISO 8601 timestamp (accepts trailing Z or numeric offset).
    Naive values are treated as UTC. Returns an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a timestamp")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(d, months):
    """Calendar-month addition; same day-of-month, clamped to month end."""
    total = d.year * 12 + (d.month - 1) + months
    y = total // 12
    m = total % 12 + 1
    day = min(d.day, monthrange(y, m)[1])
    return date(y, m, day)


def add_days(d, days):
    return d + timedelta(days=days)


def round_half_up_div(num, den):
    """round_half_up(num / den) to integer cents via Decimal."""
    q = (Decimal(num) / Decimal(den)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def ceil_div_nonnegative(num, den):
    return -((-num) // den)
