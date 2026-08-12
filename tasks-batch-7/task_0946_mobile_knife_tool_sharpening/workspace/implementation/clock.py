"""The logical clock (PRD 2.5) and the single timestamp rendering rule.

Timestamp adjudication, applied uniformly:

  (i)   Server-generated instants (created_at, updated_at, completed_at,
        delivered_at, issued_at, returned_at, applied_at, paused_at,
        hold_expires_at, last_released_at, api_request_timestamp) are rendered
        as ISO 8601 UTC with exactly three fractional digits and a literal `Z`
        suffix: YYYY-MM-DDTHH:MM:SS.mmmZ   (PRD 2.2 / 2.4).
  (ii)  A caller-supplied instant is echoed verbatim, never re-rendered.  The
        only caller-supplied instant in this API is `to_iso8601` on
        POST /_clock/set_current_utc, whose response field `current_utc`
        therefore returns the exact string the caller sent.  Before any client
        sets it, `current_utc` reads the literal PRD default
        `2026-05-01T00:00:00Z`.
  (iii) An instant DERIVED from another instant is rendered under the same rule
        as the instant it derives from.  Every derived stamp in this system
        (due_at = issued_at + 14 days, hold_expires_at = clock + 72 hours,
        the re-stamped delivered_at, the proration/cycle dates) derives from
        the clock instant, i.e. from a server-generated instant, so it renders
        under rule (i).  No derived value ever derives from a caller-supplied
        string, so a `.000Z`-versus-`Z` mismatch between an input and a value
        derived from it cannot arise.
"""

import datetime
import re

from constants import DEFAULT_CLOCK_UTC

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)

UTC = datetime.timezone.utc


class LogicalClock(object):
    """Holds the current logical instant plus the caller's literal string."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._instant = parse_instant(DEFAULT_CLOCK_UTC)
        self._literal = DEFAULT_CLOCK_UTC

    @property
    def now(self):
        """The current logical instant as a timezone-aware datetime."""
        return self._instant

    @property
    def literal(self):
        """The string form to report from the clock endpoint (rule ii)."""
        return self._literal

    def today(self):
        return self._instant.date()

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


def parse_date(text):
    """Parse a strict YYYY-MM-DD calendar date, or return None."""
    if not isinstance(text, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return None
    try:
        return datetime.date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:
        return None


def parse_hhmm(text):
    """Parse a strict HH:MM local time into minutes-since-midnight, or None."""
    if not isinstance(text, str) or not re.match(r"^\d{2}:\d{2}$", text):
        return None
    hour, minute = int(text[0:2]), int(text[3:5])
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def parse_period(text):
    """Parse a strict YYYY-MM billing period into (year, month), or None."""
    if not isinstance(text, str) or not re.match(r"^\d{4}-\d{2}$", text):
        return None
    year, month = int(text[0:4]), int(text[5:7])
    if month < 1 or month > 12:
        return None
    return (year, month)


def render_instant(value):
    """Rule (i): ISO 8601 UTC with exactly three fractional digits."""
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


def render_date(value):
    if value is None:
        return None
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def render_hhmm(minutes):
    if minutes is None:
        return None
    return "%02d:%02d" % (minutes // 60, minutes % 60)


clock = LogicalClock()


def now():
    return clock.now


def today():
    return clock.today()


def now_iso():
    return render_instant(clock.now)
