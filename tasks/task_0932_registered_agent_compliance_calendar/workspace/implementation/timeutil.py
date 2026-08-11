"""The logical clock, the business calendar and the business-hour cursor.

ADJUDICATION OF FRICTION 1 -- created_at / updated_at source.
PRD 2.5 states without qualification that "Every 'current instant' and 'current
date' this document refers to -- including the created_at and updated_at stamps
of Section 2.4 [...] -- is read from the logical clock", and that the platform
"does not read the host machine's wall clock for any business decision" and
"never falls back to wall-clock time".  Reading: THE LOGICAL CLOCK.  This is the
reading that keeps the largest number of declared behaviours reachable -- every
assertion about a stamped instant becomes derivable from a clock the caller
drives, and nothing in the document becomes unreachable.  There is exactly one
instant renderer in the whole server (`render_instant` below) and every
server-written instant passes through it.
"""

import calendar as _calendar
import datetime as _dt
import re

from constants import (
    BUSINESS_DAY_END_HOUR_UTC,
    BUSINESS_DAY_START_HOUR_UTC,
    CLOCK_DEFAULT_UTC,
    OBSERVED_HOLIDAYS,
)

UTC = _dt.timezone.utc

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# rendering / parsing
# ---------------------------------------------------------------------------
def render_instant(value):
    """THE single renderer for every server-written instant.

    Form: YYYY-MM-DDTHH:MM:SS.mmmZ -- ISO 8601 UTC with exactly three
    fractional digits, always present, always 'Z' (PRD 2.2 / 2.4).
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def render_date(value):
    """Renderer for every ISO calendar date (YYYY-MM-DD)."""
    if value is None:
        return None
    return value.isoformat()


def parse_instant(text):
    """Parse a caller-supplied ISO 8601 instant.  Returns None when malformed."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(text):
    """Parse a caller-supplied ISO date.  Returns None when malformed."""
    if not isinstance(text, str) or not _ISO_DATE_RE.match(text.strip()):
        return None
    try:
        return _dt.date.fromisoformat(text.strip())
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# the logical clock
# ---------------------------------------------------------------------------
class LogicalClock:
    def __init__(self):
        self.reset()

    def reset(self):
        self._now = parse_instant(CLOCK_DEFAULT_UTC)

    def now(self):
        return self._now

    def today(self):
        return self._now.date()

    def set(self, instant):
        previous = self._now
        self._now = instant
        return previous


CLOCK = LogicalClock()


def now():
    return CLOCK.now()


def today():
    return CLOCK.today()


# ---------------------------------------------------------------------------
# business calendar
# ---------------------------------------------------------------------------
def is_business_day(day):
    if day.weekday() >= 5:  # Saturday == 5, Sunday == 6
        return False
    return day.isoformat() not in OBSERVED_HOLIDAYS


def roll_forward(day):
    """PRD 2.5 'the forward roll': advance while non-business; never backwards."""
    guard = 0
    while not is_business_day(day):
        day = day + _dt.timedelta(days=1)
        guard += 1
        if guard > 4000:  # pragma: no cover - defensive
            break
    return day


def next_business_day(day):
    return roll_forward(day + _dt.timedelta(days=1))


def days_in_month(year, month):
    return _calendar.monthrange(year, month)[1]


def clamp_day(year, month, day):
    return min(day, days_in_month(year, month))


def add_days(day, count):
    return day + _dt.timedelta(days=count)


def day_diff(later, earlier):
    return (later - earlier).days


# ---------------------------------------------------------------------------
# the business-hour cursor (PRD 2.5)
# ---------------------------------------------------------------------------
def advance_business_hours(instant, hours):
    """Advance an instant by a whole number of business hours.

    Normalisation: a cursor that is not on a business day, or is at/after
    17:00 UTC, moves to 09:00 UTC of the next business day; a cursor on a
    business day strictly before 09:00 UTC moves to 09:00 UTC of that day;
    otherwise it stays put.  Then whole spans of the 09:00-17:00 window are
    consumed until the requirement fits.
    """
    cursor = instant.astimezone(UTC)
    day_start = cursor.replace(
        hour=BUSINESS_DAY_START_HOUR_UTC, minute=0, second=0, microsecond=0
    )
    day_end = cursor.replace(
        hour=BUSINESS_DAY_END_HOUR_UTC, minute=0, second=0, microsecond=0
    )
    if not is_business_day(cursor.date()) or cursor >= day_end:
        nxt = next_business_day(cursor.date())
        cursor = _dt.datetime(
            nxt.year, nxt.month, nxt.day, BUSINESS_DAY_START_HOUR_UTC, tzinfo=UTC
        )
    elif cursor < day_start:
        cursor = day_start

    remaining = hours
    guard = 0
    while remaining > 0:
        end_of_day = cursor.replace(
            hour=BUSINESS_DAY_END_HOUR_UTC, minute=0, second=0, microsecond=0
        )
        left = (end_of_day - cursor).total_seconds() / 3600.0
        if remaining <= left:
            return cursor + _dt.timedelta(hours=remaining)
        remaining -= left
        nxt = next_business_day(cursor.date())
        cursor = _dt.datetime(
            nxt.year, nxt.month, nxt.day, BUSINESS_DAY_START_HOUR_UTC, tzinfo=UTC
        )
        guard += 1
        if guard > 4000:  # pragma: no cover - defensive
            break
    return cursor
