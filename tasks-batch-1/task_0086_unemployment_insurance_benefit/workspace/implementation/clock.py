"""Server clock. Supports the /_clock/set_current_utc test hook (PRD §3.10).

When the clock has been set, all created_at/updated_at stamps and all
date-derived computed fields use that instant until reset; otherwise it
defaults to wall-clock UTC.
"""
from datetime import datetime, timezone


class Clock:
    def __init__(self):
        self._fixed = None  # datetime (aware, UTC) or None

    def reset(self):
        self._fixed = None

    def set_iso(self, iso_str):
        self._fixed = parse_instant(iso_str)

    def now(self):
        if self._fixed is not None:
            return self._fixed
        return datetime.now(timezone.utc)

    def now_iso(self):
        return format_instant(self.now())

    def today(self):
        """Date portion of 'now' as a date object (UTC)."""
        return self.now().date()


def parse_instant(iso_str):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if not isinstance(iso_str, str):
        raise ValueError("not a string")
    s = iso_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


clock = Clock()
