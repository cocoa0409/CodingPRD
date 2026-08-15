"""The logical clock (PRD 2.4) and the timestamp rendering rules.

Timestamp adjudication, applied uniformly:

  (i)   Server-generated instants (created_at, updated_at, posted_at,
        submitted_at, pto_granted_at, decided_at, api_request_timestamp) are
        rendered as ISO 8601 UTC with exactly three fractional digits and a
        literal `Z` suffix: YYYY-MM-DDTHH:MM:SS.mmmZ  (PRD 2.2 / 2.5).
  (ii)  A caller-supplied instant is echoed verbatim, never re-rendered:
        `to_iso8601` on POST /_clock/set_current_utc (whose response field
        `current_utc` returns the exact string the caller sent),
        TariffSchedule.effective_from/effective_to, Inspection.scheduled_date /
        occurred_at, MeterExchange.window_start/window_end and
        MeterReading.period_start/period_end.
  (iii) An instant DERIVED from the server clock (reservation_expires_at =
        now + 180 days, valid_until = now + 30 days, reconciliation
        window_start/window_end) renders under rule (i).
"""

import datetime
import re

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

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


clock = LogicalClock()


def now():
    return clock.now


def now_iso():
    return render_instant(clock.now)
