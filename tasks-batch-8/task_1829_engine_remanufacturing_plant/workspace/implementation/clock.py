"""The logical clock (PRD 2.5) and timestamp rendering rules.

All timestamps the server stamps itself -- created_at, updated_at, graded_at,
sold_at, filed_at, sealed_at, closed_at, activated_at, retired_at -- are read
from a single logical clock, never the wall clock.  Before any clock-setting
call the clock reads exactly 2026-08-01T00:00:00Z.  POST /_clock/set_current_utc
advances it; its `current_utc` response echoes the caller's string verbatim.

Rendering rule for every server-stamped instant: ISO 8601 UTC with exactly
three fractional digits and a literal Z suffix: YYYY-MM-DDTHH:MM:SS.mmmZ.

Caller-supplied instants (scheduled_start/scheduled_end on an operation
perform, started_at/ended_at on a dyno test) are echoed verbatim in
responses; the parsed value is only used internally for overlap math.

Age-in-days math: whole days between two UTC instants -- the floor of the
difference in seconds divided by 86400.  For aware datetimes this is exactly
`(later - earlier).days` (timedelta.days is floor-based, including negatives).
"""

import datetime
import re

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
UTC = datetime.timezone.utc

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


class LogicalClock(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self._instant = parse_instant(DEFAULT_CLOCK_UTC)
        self._literal = DEFAULT_CLOCK_UTC

    @property
    def now(self):
        return self._instant

    @property
    def literal(self):
        return self._literal

    def set(self, instant, literal):
        self._instant = instant
        self._literal = literal


def parse_instant(text):
    """Parse an ISO 8601 instant; return an aware UTC datetime or None."""
    if not isinstance(text, str):
        return None
    m = _ISO_RE.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    offset = m.group(8)
    try:
        naive = datetime.datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset in (None, "Z", "z"):
        return naive.replace(tzinfo=UTC)
    sign = 1 if offset[0] == "+" else -1
    body = offset[1:].replace(":", "")
    delta = datetime.timedelta(hours=int(body[:2]), minutes=int(body[2:]))
    return (naive - sign * delta).replace(tzinfo=UTC)


def render_instant(value):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if value is None:
        return None
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


def age_in_days(earlier, later):
    """Whole days between two UTC instants: floor(seconds difference / 86400)."""
    if earlier is None or later is None:
        return None
    return (later - earlier).days


clock = LogicalClock()


def now():
    return clock.now
