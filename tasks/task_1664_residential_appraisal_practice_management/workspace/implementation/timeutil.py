"""The logical clock (PRD 2.4) and timestamp parsing/rendering.

Rendering contract:
  * Server-written instants whose value carries a fractional second render as
    ISO 8601 UTC with exactly three fractional digits and a trailing ``Z``
    (PRD 2.2 / 2.5).  Whole-second instants render without a fractional part,
    matching the plain ``YYYY-MM-DDTHH:MM:SSZ`` form the spec's worked
    examples use (e.g. retention pins such as 2031-08-02T00:00:00Z).
  * Caller-supplied instant strings (fee-schedule windows, the clock setter's
    own echo) are echoed back verbatim; ``parse_instant`` supplies the
    comparison value.  Comparisons are always semantic (aware datetimes).
  * Calendar-date fields (license_expiry, sale_date) stay ``YYYY-MM-DD``
    strings and are compared against the logical clock's calendar date.

The logical clock never falls back to wall-clock time; before it is set it
reads exactly 2026-08-01T00:00:00Z.
"""

import re
from datetime import date, datetime, timedelta, timezone

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ]"
    r"(\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d{1,9}))?"
    r"(?:[Zz]|[+-]\d{2}:?\d{2})?$"
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_instant(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac = m.groups()
    micro = 0
    if frac:
        micro = int((frac + "000000")[:6])
    try:
        return datetime(
            int(year), int(month), int(day),
            int(hour), int(minute), int(second), micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def is_iso_instant(value):
    return parse_instant(value) is not None


def is_date_string(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
        return True
    except ValueError:
        return False


def parse_date(value):
    if not is_date_string(value):
        return None
    return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


def render_instant(dt):
    """Render an aware datetime; three fractional digits only when the value
    carries sub-second precision (PRD 2.5's millisecond rule), else plain
    seconds form."""
    if dt is None:
        return None
    base = "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
    )
    if dt.microsecond:
        base += ".%03d" % (dt.microsecond // 1000)
    return base + "Z"


def render_meta_timestamp():
    """PRD 2.2: envelope timestamps always carry three fractional digits."""
    dt = clock.now
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def add_years(dt, years):
    """Calendar-year addition preserving month/day (clamping Feb 29)."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap target years.
        return dt.replace(year=dt.year + years, day=28)


def business_days_between(start_dt, end_dt):
    """Dates d in (start_date, end_date] whose weekday is Monday..Friday."""
    if end_dt is None or start_dt is None:
        return 0
    d = start_dt.date() + timedelta(days=1)
    last = end_dt.date()
    count = 0
    while d <= last:
        if d.weekday() < 5:
            count += 1
        d += timedelta(days=1)
    return count


class LogicalClock(object):
    """The controllable logical clock.  Never reads wall-clock time."""

    def __init__(self):
        self._now = parse_instant(DEFAULT_CLOCK_UTC)
        self._raw = DEFAULT_CLOCK_UTC

    @property
    def now(self):
        return self._now

    @property
    def raw(self):
        return self._raw

    @property
    def today(self):
        return self._now.date()

    def set(self, dt, raw):
        self._now = dt
        self._raw = raw

    def now_string(self):
        return render_instant(self._now)


clock = LogicalClock()
