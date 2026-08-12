"""Instant parsing, canonical rendering and the logical clock.

TIMESTAMP RENDERING RULE (PRD 2.4, applied uniformly to all three cases):

  (a) server-written instants (created_at, updated_at, issued_at, granted_at, ...)
      render as ISO 8601 UTC with exactly three fractional digits and a trailing Z;
  (b) caller-supplied instants that the server stores and echoes back
      (start_at, acquired_at, release_at, close_at, ...) are parsed semantically to
      an instant and re-rendered in the SAME canonical three-fractional-digit form
      -- the PRD says "the response, however, always renders the platform's own
      canonical three-fractional-digit form", so nothing is echoed byte-verbatim;
  (c) instants derived from a caller-supplied one (swap_by_at, end_at, ...) are
      computed on the parsed instant and rendered in that same canonical form.

Every comparison is a semantic instant comparison on timezone-aware datetimes.
"""

import math
import re
from datetime import datetime, timedelta, timezone

from constants import DEFAULT_CLOCK_UTC
from errors import ApiError

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}:\d{2}(\.\d+)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value, error_id="ERR_VALIDATION"):
    """Parse an ISO 8601 instant into an aware UTC datetime, or raise."""
    if not isinstance(value, str) or not _ISO_RE.match(value.strip()):
        raise ApiError(error_id, "Value is not a valid ISO 8601 instant.")
    text = value.strip()
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ApiError(error_id, "Value is not a valid ISO 8601 instant.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_instant(dt):
    """Canonical form: ISO 8601 UTC, exactly three fractional digits, trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def ceil_days(delta):
    """Whole days with any partial day rounded UP."""
    seconds = delta.total_seconds()
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds / 86400.0))


def floor_days(delta):
    seconds = delta.total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // 86400)


def floor_months(later, earlier):
    """Whole calendar months elapsed between two instants (never negative)."""
    if later <= earlier:
        return 0
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    anchor = _shift_months(earlier, months)
    while anchor > later:
        months -= 1
        anchor = _shift_months(earlier, months)
    return max(0, months)


def _shift_months(dt, months):
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def days_overlap(a_start, a_end, b_start, b_end):
    """Whole days shared by two half-open [start, end) instant intervals."""
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if end <= start:
        return 0
    return floor_days(end - start)


class LogicalClock:
    """Never falls back to wall-clock time."""

    def __init__(self):
        self._now = parse_instant(DEFAULT_CLOCK_UTC)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt
        return self._now


clock = LogicalClock()


def now():
    return clock.now()
