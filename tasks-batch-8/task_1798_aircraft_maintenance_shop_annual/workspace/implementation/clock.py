"""The shop's logical UTC clock (PRD 2.7) and timestamp rendering rules.

Timestamp adjudication, applied uniformly:

  (i)   Server-generated instants (created_at, updated_at, signed_at,
        warranty_expires_at) are rendered ISO 8601 UTC with exactly three
        fractional digits and a literal `Z` suffix: YYYY-MM-DDTHH:MM:SS.mmmZ.
  (ii)  Caller-supplied instants (HangarSlot.starts_at / ends_at) are echoed
        verbatim, never re-rendered.  Parsed copies are kept alongside for
        interval arithmetic.
  (iii) An instant derived from the logical clock (warranty_expires_at =
        RTS instant + 90 days) renders under rule (i).

The logical clock boots at exactly 2026-08-01T00:00:00Z and never falls back
to wall-clock time; POST /api/_clock/set_current_utc is the only way it moves.
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
    def __init__(self):
        self._instant = parse_instant(DEFAULT_CLOCK_UTC)

    @property
    def now(self):
        return self._instant

    def set(self, instant):
        self._instant = instant


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
