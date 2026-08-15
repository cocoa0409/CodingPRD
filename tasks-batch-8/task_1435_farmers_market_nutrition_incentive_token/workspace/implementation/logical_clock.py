"""Logical clock (PRD §2.4).

All temporal rules evaluate against this clock, never wall-clock time.
Startup default is exactly 2026-08-01T00:00:00Z. The clock may only be
moved via POST /_clock/set_current_utc.

All timestamps produced by the server (created_at, updated_at, approved_at,
disputed_at, meta.api_request_timestamp, current_utc) are derived from this
clock, quantized (truncated) to milliseconds so that the stored value and
its serialized form compare identically.
"""

from datetime import datetime, timezone

_DEFAULT_ISO = "2026-08-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def quantize_ms(dt):
    """Truncate a datetime to whole milliseconds."""
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def format_iso(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits."""
    dt = quantize_ms(dt.astimezone(timezone.utc))
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class LogicalClock:
    def __init__(self):
        self._now = quantize_ms(_parse_iso(_DEFAULT_ISO))

    def now(self):
        return self._now

    def set(self, dt):
        self._now = quantize_ms(dt)
        return self._now

    def now_iso(self):
        return format_iso(self._now)

    def current_date_str(self):
        return self._now.strftime("%Y-%m-%d")


# Module-level singleton; fresh per process boot (in-memory only).
CLOCK = LogicalClock()
