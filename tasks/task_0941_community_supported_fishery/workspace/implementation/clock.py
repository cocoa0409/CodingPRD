"""The logical clock and the ONE instant renderer (PRD 2.4).

PRD 2.4: "All timestamps in this system, whether stored or returned, are ISO
8601 instants in UTC rendered with exactly three fractional-second digits and a
trailing Z."  That is a blanket rule over *every* returned instant, so this
module owns the single rendering function used by every serializer.  There is
no second code path that formats an instant.

PRD 2.4: "Time in this system is a logical clock, not wall-clock time.  Before
any client sets it, the clock reads exactly its declared default
CLOCK_DEFAULT_UTC, which is the instant 2026-05-01T00:00:00Z, and it never
falls back to real time."  Every system-written instant in this service --
created_at, updated_at, landed_at, requested_at, recorded_at, true_up_run_at
and the envelope's api_request_timestamp -- is therefore stamped from here and
never from datetime.now().
"""
import re
from datetime import datetime, timedelta, timezone

from constants import CLOCK_DEFAULT_UTC

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse an ISO 8601 UTC instant.  Returns None when the value is not one.

    An explicit non-UTC offset is normalised to UTC; a bare instant with no
    offset is read as UTC, which is the only zone this system speaks.
    """
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro,
                      tzinfo=timezone.utc)
    except ValueError:
        return None
    off = m.group(8)
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        body = off[1:].replace(":", "")
        delta = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * delta
    return dt


def render_instant(dt):
    """Render an instant with exactly three fractional-second digits and a Z.

    This is the system's single instant-rendering function.  It is applied
    uniformly to all three classes of instant:
      (i)   server-minted instants (created_at, updated_at, landed_at,
            requested_at, recorded_at, true_up_run_at, api_request_timestamp);
      (ii)  caller-supplied instants echoed back (start_date, end_date,
            opens_at, closes_at, species_open_date, species_close_date,
            the clock's current_utc);
      (iii) instants derived from a caller-supplied instant (scheduled_at,
            cutoff_at).
    PRD 2.4 makes no distinction between the three -- "whether stored or
    returned" -- and PRD 3.2's worked example confirms it: a season starting
    "2026-05-04T00:00:00Z" schedules its week-11 box at
    "2026-07-13T00:00:00.000Z".
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _default_now():
    return parse_instant(CLOCK_DEFAULT_UTC)


class _Clock:
    """Holds the single logical-clock instant for this process."""

    def __init__(self):
        self.current = _default_now()

    def now(self):
        return self.current

    def set(self, instant):
        self.current = instant

    def reset(self):
        self.current = _default_now()


CLOCK = _Clock()


def now():
    """The current logical-clock instant, as an aware UTC datetime."""
    return CLOCK.now()
