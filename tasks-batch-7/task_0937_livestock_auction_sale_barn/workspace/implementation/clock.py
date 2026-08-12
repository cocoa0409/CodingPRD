"""The logical sale clock and the SINGLE instant renderer (PRD 2.4).

There is no wall-clock read anywhere in this implementation. The clock starts
at DEFAULT_CLOCK_UTC on every boot and only an administrator moves it.

TIMESTAMP RENDERING POLICY (one producer, stated once):

  * Every SERVER-MINTED instant - created_at, updated_at, checked_in_at,
    penned_at, released_at, opened_at, captured_at, completed_at,
    last_move_completed_at, dispatched_at and the envelope's
    api_request_timestamp - is rendered by ``render_instant()`` as
    ``YYYY-MM-DDTHH:MM:SS.mmmZ`` (ISO 8601 UTC, exactly three fractional
    digits), because PRD 2.4 pins "three fractional digits".

  * Every CALLER-SUPPLIED instant string is echoed VERBATIM as the caller
    wrote it: PenMove.scheduled_start_at, and the clock endpoint's
    current_utc (which echoes the administrator's to_iso8601, or the boot
    default string).

  * The one instant DERIVED from a caller-supplied string,
    PenMove.scheduled_end_at, is rendered by ``render_derived()`` in the
    style of its own source string (same fractional-digit count, same
    Z/offset suffix), so start and end always read alike.

  * Date-valued fields are echoed verbatim; the one derived date,
    InspectionRecord.valid_through, is rendered YYYY-MM-DD.
"""
import re
from datetime import datetime, timedelta, timezone

from config import DEFAULT_CLOCK_UTC

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


class Clock:
    def __init__(self):
        self.reset()

    def reset(self):
        self._dt = parse_instant(DEFAULT_CLOCK_UTC)
        self._source = DEFAULT_CLOCK_UTC

    def now(self):
        """Current logical instant as an aware datetime."""
        return self._dt

    def now_date(self):
        return self._dt.date()

    def current_utc_string(self):
        """Verbatim echo of the string the clock was last set from."""
        return self._source

    def set(self, iso_string, dt):
        self._dt = dt
        self._source = iso_string


def parse_instant(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, suffix = m.groups()
    try:
        micro = 0
        if frac:
            micro = int(round(float(frac) * 1_000_000))
        dt = datetime(int(year), int(month), int(day), int(hour), int(minute),
                      int(second), micro, tzinfo=timezone.utc)
    except ValueError:
        return None
    if suffix and suffix not in ("Z", "z"):
        sign = 1 if suffix[0] == "+" else -1
        body = suffix[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:]))
        dt = dt - sign * offset
    return dt


def render_instant(dt):
    """THE producer for every server-minted instant: 3 fractional digits, Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def _style_of(source):
    """(fractional digit count, suffix) of a caller-supplied instant string."""
    if not isinstance(source, str):
        return 3, "Z"
    m = _ISO_RE.match(source.strip())
    if not m:
        return 3, "Z"
    frac, suffix = m.group(7), m.group(8)
    digits = len(frac) - 1 if frac else 0
    return digits, (suffix if suffix else "Z")


def render_derived(dt, source):
    """Render an instant derived from ``source`` in that source's own style."""
    if dt is None:
        return None
    digits, suffix = _style_of(source)
    dt = dt.astimezone(timezone.utc)
    base = "%04d-%02d-%02dT%02d:%02d:%02d" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    if digits:
        micro = "%06d" % dt.microsecond
        if digits <= 6:
            frac = micro[:digits]
        else:
            frac = micro + "0" * (digits - 6)
        base += "." + frac
    if suffix in ("Z", "z"):
        return base + "Z"
    return base + "+00:00" if suffix else base + "Z"


DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date, or None."""
    if not isinstance(value, str):
        return None
    m = DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        tzinfo=timezone.utc).date()
    except ValueError:
        return None


def render_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


# The one clock instance, built after its helpers exist.
clock = Clock()
