"""The logical clock (PRD 2.5) and the single timestamp rendering rule.

Timestamp adjudication, applied uniformly:

  (i)   Server-generated instants (created_at, updated_at, placed_at,
        released_at, dispatched_at, returned_at) are rendered from the
        logical clock as ISO 8601 UTC with exactly three fractional digits
        and a literal `Z` suffix: YYYY-MM-DDTHH:MM:SS.mmmZ  (PRD 2.2 / 2.4).
  (ii)  A caller-supplied instant is echoed verbatim, never re-rendered.  The
        only caller-supplied instant in this API is `to_iso8601` on
        POST /cargo/_clock/set_current_utc, whose response field
        `current_utc` therefore returns the exact string the caller sent.
        Before any client sets it, the clock reads the literal PRD default
        `2026-08-01T00:00:00Z` and never falls back to wall-clock time.
"""

import datetime
import re

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)

UTC = datetime.timezone.utc


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


def wall_clock_iso():
    """api_request_timestamp: wall-clock ISO 8601 UTC, three fractional digits.

    PRD 2.5 enumerates exactly which stamps flow from the logical clock
    (created_at, updated_at, placed_at, released_at, dispatched_at,
    returned_at); the envelope's api_request_timestamp is not among them.
    """
    now = datetime.datetime.now(UTC)
    return render_instant(now)
