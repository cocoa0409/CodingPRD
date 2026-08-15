"""Shared helpers: ids, timestamps, the logical clock, calendar math.

No business rule reads the machine wall clock; every domain "now" comes from
the logical CLOCK (PRD 2.6). The wall clock is used only for the
meta.api_request_timestamp envelope field and created_at/updated_at stamps.
"""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def wall_now_ts() -> str:
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# ISO 8601 parsing / rendering
# ---------------------------------------------------------------------------

_ISO_INSTANT = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(text):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(text, str):
        return None
    m = _ISO_INSTANT.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt.replace(tzinfo=timezone.utc)


def parse_clock_input(text):
    """Accept a full ISO 8601 instant or a bare YYYY-MM-DD date (midnight UTC)."""
    dt = parse_instant(text)
    if dt is not None:
        return dt
    d = parse_date(text)
    if d is None:
        return None
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def render_instant(dt):
    """Server-written instant: YYYY-MM-DDTHH:MM:SS.mmmZ (three digits always)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:03d}Z".format(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_date(text):
    """Parse a caller-supplied YYYY-MM-DD calendar date, or None."""
    if not isinstance(text, str):
        return None
    m = _ISO_DATE.match(text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.6): fixed startup instant, never wall-clock fallback.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


class LogicalClock:
    def __init__(self):
        self._dt = parse_instant(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def set(self, to: datetime) -> datetime:
        self._dt = to
        return self._dt


CLOCK = LogicalClock()


def now() -> datetime:
    return CLOCK.now()


def clock_date() -> date:
    """All date comparisons against the clock use the UTC date."""
    return CLOCK.now().astimezone(timezone.utc).date()


# ---------------------------------------------------------------------------
# Reporting periods: 'YYYY-Qn' -> inclusive calendar quarter date range
# (PRD 3.6). Q1 = Jan 1..Mar 31, Q2 = Apr 1..Jun 30, Q3 = Jul 1..Sep 30,
# Q4 = Oct 1..Dec 31.
# ---------------------------------------------------------------------------

_PERIOD = re.compile(r"^(\d{4})-Q([1-4])$")
_QUARTER_END_DAY = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def parse_period(text):
    """Return (year, quarter, start_date, end_date) or None."""
    if not isinstance(text, str):
        return None
    m = _PERIOD.match(text.strip())
    if not m:
        return None
    year = int(m.group(1))
    quarter = int(m.group(2))
    start_month = (quarter - 1) * 3 + 1
    end_month, end_day = _QUARTER_END_DAY[quarter]
    return (year, quarter, date(year, start_month, 1), date(year, end_month, end_day))
