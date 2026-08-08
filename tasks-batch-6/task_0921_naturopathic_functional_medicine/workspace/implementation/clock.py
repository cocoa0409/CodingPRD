"""The logical clock and the single timestamp-rendering rule.

Rendering rule (one rule, applied everywhere):

  * A caller-supplied instant string is echoed back VERBATIM. It is never
    re-formatted, never gains or loses fractional digits.
  * Every instant the server derives from the logical clock (`created_at`,
    `updated_at`, `*_at` stamps, and instants computed from them such as
    `expires_at`, `sla_due_at`, `next_review_due_at`) is rendered with the
    fractional-digit style of the string that most recently SET the clock.
    The clock starts at "2026-05-01T00:00:00Z", i.e. no fractional digits, so
    an untouched clock stamps "2026-05-01T00:00:00Z" and never
    "2026-05-01T00:00:00.000Z".
  * `meta.api_request_timestamp` is the one field PRD 2.2 pins explicitly at
    three fractional digits, and it always carries exactly three.

Date-only fields are plain YYYY-MM-DD calendar dates.
"""

import re
from datetime import datetime, timedelta, timezone

from config import DEFAULT_CLOCK_UTC

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(value):
    """Parse an ISO-8601 instant string into an aware UTC datetime.

    Returns None when the value is not a well-formed instant string.
    """
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, offset = m.groups()
    try:
        micro = 0
        if frac:
            digits = (frac[1:] + "000000")[:6]
            micro = int(digits)
        dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        try:
            off = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        except ValueError:
            return None
        dt = dt - sign * off
    return dt


def fractional_style(value):
    """The fractional-second suffix carried by an instant string ('' or '.123')."""
    m = _ISO_RE.match(value.strip()) if isinstance(value, str) else None
    if not m:
        return ""
    return m.group(7) or ""


def parse_date(value):
    """Parse a plain YYYY-MM-DD calendar date. Returns None when malformed."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    except ValueError:
        return None


def render_date(d):
    return d.isoformat() if d is not None else None


class LogicalClock:
    """Server-wide logical clock. Never falls back to the host wall clock."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._raw = DEFAULT_CLOCK_UTC
        self._dt = parse_instant(DEFAULT_CLOCK_UTC)
        self._frac = fractional_style(DEFAULT_CLOCK_UTC)

    def set(self, raw_value):
        dt = parse_instant(raw_value)
        self._raw = raw_value
        self._dt = dt
        self._frac = fractional_style(raw_value)
        return self._raw

    @property
    def raw(self):
        return self._raw

    def now(self):
        """Current logical instant as an aware UTC datetime."""
        return self._dt

    def today(self):
        """Current logical calendar date."""
        return self._dt.date()

    def render(self, dt):
        """Render a derived instant in the clock's current fractional style."""
        if dt is None:
            return None
        base = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        if not self._frac:
            return base + "Z"
        width = len(self._frac) - 1
        micro = dt.astimezone(timezone.utc).microsecond
        digits = "{:06d}".format(micro)
        if width <= 6:
            digits = digits[:width]
        else:
            digits = digits + "0" * (width - 6)
        return base + "." + digits + "Z"

    def stamp(self):
        """The current logical instant, rendered."""
        return self.render(self._dt)

    def meta_timestamp(self):
        """PRD 2.2 pins this field at exactly three fractional digits."""
        dt = self._dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".{:03d}".format(
            dt.microsecond // 1000
        ) + "Z"


clock = LogicalClock()
