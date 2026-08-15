"""Logical clock and timestamp rendering rules (PRD sections 2.4 / 2.5).

  * Server-written instants render as ISO 8601 UTC with exactly three
    fractional digits and a trailing ``Z`` (``render_server``).
  * Caller-supplied instants are echoed back byte for byte; the raw request
    string is stored on the row and never reformatted.  ``parse_instant`` is
    used only to obtain a comparison value.
  * The clock endpoint's ``current_utc`` reproduces the operator-supplied
    ``to_iso8601`` verbatim.
  * All instant comparisons are semantic (aware datetimes), never strings.
"""

import re
from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt]"
    r"(\d{2}):(\d{2}):(\d{2})"
    r"(?:\.(\d{1,9}))?"
    r"(Z|z|\+00:00|\+0000)?$"
)


def parse_instant(value):
    """Parse an ISO 8601 UTC instant.  Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, _tz = m.groups()
    micro = int((frac + "000000")[:6]) if frac else 0
    try:
        return datetime(
            int(year), int(month), int(day),
            int(hour), int(minute), int(second), micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def render_server(dt):
    """A server-written instant: three fractional digits, trailing ``Z``."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day,
        dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def whole_days_between(start, end):
    """floor((end - start) in whole days); timedelta.days already floors."""
    return (end - start).days


class LogicalClock(object):
    """Never reads wall-clock time.  Starts at the PRD 2.4 fixed instant."""

    def __init__(self):
        self._now = parse_instant(DEFAULT_CLOCK_UTC)
        self._raw = DEFAULT_CLOCK_UTC

    @property
    def now(self):
        return self._now

    @property
    def raw(self):
        return self._raw

    def set(self, dt, raw):
        self._now = dt
        self._raw = raw

    def now_server_string(self):
        return render_server(self._now)


clock = LogicalClock()
