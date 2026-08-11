"""The logical clock and the timestamp rendering rules of PRD section 2.5.

Rendering contract, implemented literally:

  rule 1  Every *server-written* instant renders as ISO 8601 UTC with EXACTLY
          three fractional digits and a trailing ``Z``.  ``render_server()`` is
          the single funnel for those fields.
  rule 2  A *derived* instant (package.expires_at = generated_at + 180d,
          appraisal.valid_until_at = certified_at + 1095d) is server-written and
          therefore also carries three fractional digits: it goes through the
          same funnel.
  rule 3  Every *caller-supplied* instant is echoed back byte for byte.  Those
          fields are stored as the raw request string and never reformatted;
          ``parse_instant()`` is used only to obtain a comparison value.
  rule 4  The clock endpoint's ``current_utc`` reproduces the operator-supplied
          ``to_iso8601`` verbatim (same treatment as rule 3).
  rule 5  All instant comparisons are semantic: everything is compared as an
          aware ``datetime``, never as a string.
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


def parse_instant(value):
    """Parse an ISO 8601 UTC instant.  Returns an aware datetime or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
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


def render_server(dt):
    """Rule 1/2: a server-written instant, three fractional digits, ``Z``."""
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


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def whole_days_between(start, end):
    """floor((end - start) in whole days).  timedelta.days already floors."""
    return (end - start).days


class LogicalClock(object):
    """Never reads wall-clock time.  Starts at PRD 2.5's fixed instant."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._now = parse_instant(DEFAULT_CLOCK_UTC)
        self._raw = DEFAULT_CLOCK_UTC

    @property
    def now(self):
        return self._now

    @property
    def raw(self):
        """Rule 4: the operator-supplied string, verbatim."""
        return self._raw

    def set(self, dt, raw):
        self._now = dt
        self._raw = raw

    def now_server_string(self):
        return render_server(self._now)


clock = LogicalClock()
