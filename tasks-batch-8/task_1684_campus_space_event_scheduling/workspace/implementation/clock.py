"""The logical clock (PRD 2.4) and the timestamp rendering rules (PRD 2.5).

Rendering contract:

  * Every server-written instant renders as ISO 8601 UTC with EXACTLY three
    fractional digits and a trailing ``Z`` (``render_server``).
  * Caller-supplied instants are stored as the raw request string and echoed
    back byte for byte; ``parse_instant`` is used only to obtain a comparison
    value.
  * The clock endpoint's ``current_utc`` reproduces the operator-supplied
    ``to_iso8601`` verbatim.
  * All instant comparisons are semantic: aware ``datetime`` objects, never
    strings.

The clock starts at exactly 2026-08-01T00:00:00Z and never reads wall-clock
time.
"""

import re
from datetime import datetime, timedelta, timezone

from constants import DEFAULT_CLOCK_UTC

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt]"
    r"(\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d{1,9}))?"
    r"(Z|z|\+00:00|\+0000)?$"
)

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

_HHMM_RE = re.compile(r"^(\d{2}):(\d{2})$")


def parse_instant(value):
    """Parse an ISO 8601 UTC instant (or a bare ``YYYY-MM-DD`` date, taken as
    UTC midnight).  Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    m = _DATE_RE.match(value)
    if m:
        try:
            return datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc
            )
        except ValueError:
            return None
    m = _ISO_RE.match(value)
    if not m:
        return None
    year, month, day, hour, minute, second, frac, _tz = m.groups()
    micro = 0
    if frac:
        micro = int((frac + "000000")[:6])
    try:
        return datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            int(second),
            micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def parse_hhmm(value):
    """Parse an ``HH:MM`` UTC time-of-day.  Returns minutes since midnight or
    None."""
    if not isinstance(value, str):
        return None
    m = _HHMM_RE.match(value.strip())
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def render_server(dt):
    """A server-written instant: three fractional digits, trailing ``Z``."""
    if dt is None:
        return None
    millis = dt.microsecond // 1000
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        millis,
    )


class LogicalClock(object):
    """The single test-driving clock.  Never reads wall-clock time."""

    def __init__(self):
        self._now = parse_instant(DEFAULT_CLOCK_UTC)
        self._raw = DEFAULT_CLOCK_UTC

    @property
    def now(self):
        return self._now

    @property
    def raw(self):
        """The operator-supplied string, verbatim."""
        return self._raw

    def set(self, dt, raw):
        self._now = dt
        self._raw = raw

    def now_server_string(self):
        return render_server(self._now)


clock = LogicalClock()


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_days(dt, days):
    return dt + timedelta(days=days)
