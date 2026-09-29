"""Logical clock.

PRD section 1 / 2.4: before any request the logical clock reads exactly
2026-08-01T00:00:00Z and it never falls back to real wall-clock time.
Every date comparison, created_at / updated_at and every *_at stamp is taken
from this clock.
"""
from datetime import datetime, timezone

INITIAL_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def format_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_instant(raw):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock(object):
    def __init__(self):
        self.current = INITIAL_UTC

    def reset(self):
        self.current = INITIAL_UTC

    def now(self):
        return self.current

    def date(self):
        return self.current.date()

    def now_iso(self):
        return format_instant(self.current)

    def set(self, dt):
        self.current = dt.astimezone(timezone.utc)
        return self.current


clock = LogicalClock()
