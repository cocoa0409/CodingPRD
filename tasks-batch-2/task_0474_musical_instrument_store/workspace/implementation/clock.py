"""Server-controlled logical clock.

On startup reads exactly 2026-01-01T00:00:00Z. A StoreManager may set it via
POST /_clock/set_current_utc. All created_at/updated_at stamps and chronological
replay use this clock; the server never falls back to wall-clock time.

Timestamps are rendered ISO 8601 UTC with exactly three fractional digits.
"""

from datetime import datetime, timezone

_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self._now = _DEFAULT

    def now(self):
        return self._now

    def set_iso(self, iso_str):
        self._now = parse_iso(iso_str)

    def stamp(self):
        return format_iso(self._now)


def parse_iso(iso_str):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if not isinstance(iso_str, str):
        raise ValueError("timestamp must be a string")
    s = iso_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_iso(dt):
    """Render an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % millis
