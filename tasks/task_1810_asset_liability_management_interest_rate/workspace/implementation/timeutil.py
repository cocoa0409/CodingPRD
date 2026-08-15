"""Logical clock (PRD 2.4) plus ISO 8601 and YYYY-MM helpers.

Rendering contract:
  - Server-written instants render as ISO 8601 UTC with exactly three
    fractional digits and a trailing ``Z`` (``render``).
  - Caller-supplied instants (e.g. breach ``due_date``) are stored raw and
    echoed verbatim; ``parse_instant`` is used only for comparisons.
  - The clock endpoint's ``current_utc`` echoes the operator-supplied
    ``to_iso8601`` verbatim.
  - Month fields are ``YYYY-MM`` strings; all month comparisons are on
    calendar month indices (PRD 2.4).
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
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_instant(value):
    """Parse an ISO 8601 UTC instant. Returns an aware datetime or None."""
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


def render(dt):
    """Server-written instant: three fractional digits, trailing Z."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day,
        dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_month(value):
    """'YYYY-MM' -> (year, month) tuple, or None when malformed."""
    if not isinstance(value, str):
        return None
    m = _MONTH_RE.match(value.strip())
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if month < 1 or month > 12:
        return None
    return (year, month)


def month_index(value):
    """Calendar month index of a 'YYYY-MM' string, or None when malformed."""
    ym = parse_month(value)
    if ym is None:
        return None
    return ym[0] * 12 + (ym[1] - 1)


def add_days(dt, days):
    return dt + timedelta(days=days)


class LogicalClock(object):
    """Never reads wall-clock time. Starts at PRD 2.4's fixed instant."""

    def __init__(self):
        self._now = parse_instant(DEFAULT_CLOCK_UTC)
        self._raw = DEFAULT_CLOCK_UTC

    @property
    def now(self):
        return self._now

    @property
    def raw(self):
        """The operator-supplied ``to_iso8601`` string, verbatim."""
        return self._raw

    def set(self, dt, raw):
        self._now = dt
        self._raw = raw

    def now_string(self):
        return render(self._now)

    def period_month(self):
        return "%04d-%02d" % (self._now.year, self._now.month)

    def current_month_index(self):
        return self._now.year * 12 + (self._now.month - 1)


clock = LogicalClock()
