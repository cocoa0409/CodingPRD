"""The logical clock, the single instant producer and calendar arithmetic.

TIMESTAMP POLICY (three cases, applied everywhere without exception):

  1. Server-minted instants  -- ``created_at``, ``updated_at`` and
     ``api_request_timestamp``.  Rendered by :func:`render_instant` as
     ``YYYY-MM-DDTHH:MM:SS.mmmZ`` with EXACTLY three fractional digits and a
     trailing ``Z`` (PRD 2.2 / 2.4).  Their value is the LOGICAL clock, never
     the host wall clock.

  2. Caller-supplied instant strings -- the ``to_iso8601`` field of
     ``POST /_clock/set_current_utc`` and every caller-supplied ISO *date*
     (``scheduled_date``, ``route_date``, ``cert_expires_on``, ...).  These are
     echoed BYTE-VERBATIM exactly as received; they are never re-rendered.  An
     input of ``2026-06-01T00:00:00Z`` comes back as ``2026-06-01T00:00:00Z``
     and NOT as ``2026-06-01T00:00:00.000Z``.

  3. Derived instants -- values computed from a source string render in the
     style of that source.  Every derived value in this specification is
     derived from an ISO calendar DATE (``next_due_on`` from
     ``last_completed_on``, ``due_on`` from ``scheduled_date``, ``completed_on``
     from the clock date, ...), so they render as ``YYYY-MM-DD``, matching
     their sources.
"""

from datetime import date, datetime, timedelta, timezone

from .constants import DAYS_PER_WEEK, DEFAULT_CLOCK_UTC, WEEKDAYS


# --------------------------------------------------------------------------
# The one and only instant producer.
# --------------------------------------------------------------------------
def render_instant(dt):
    """Render a server-minted instant as ISO 8601 UTC with 3 fractional digits."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def render_date(d):
    """Render a derived calendar date in the style of its ISO-date sources."""
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_iso_instant(value):
    """Parse a caller-supplied ISO 8601 instant.  Returns None when unusable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def parse_iso_date(value):
    """Parse a caller-supplied ISO calendar date.  Returns None when unusable."""
    if not isinstance(value, str) or isinstance(value, bool):
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def weekday_token(d):
    """Weekday token of an ISO date; MON is index 0 through SUN at index 6."""
    return WEEKDAYS[d.weekday()]


def add_days(d, n):
    """Elapsed-duration day arithmetic: D + n days."""
    return d + timedelta(days=n)


def add_weeks(d, weeks):
    """"N weeks after D" means D plus N * DAYS_PER_WEEK calendar days."""
    return d + timedelta(days=weeks * DAYS_PER_WEEK)


def day_difference(later, earlier):
    """Whole-calendar-day difference of ``later`` minus ``earlier``."""
    return (later - earlier).days


class LogicalClock:
    """The server's logical clock.  It never falls back to real time."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._raw = DEFAULT_CLOCK_UTC
        self._dt = parse_iso_instant(DEFAULT_CLOCK_UTC)

    def set(self, raw, parsed):
        # `raw` is retained byte-verbatim so the clock endpoint can echo it.
        self._raw = raw
        self._dt = parsed

    @property
    def raw(self):
        return self._raw

    @property
    def now(self):
        return self._dt

    @property
    def today(self):
        return self._dt.date()

    @property
    def today_iso(self):
        return render_date(self._dt.date())

    def instant(self):
        return render_instant(self._dt)


clock = LogicalClock()
