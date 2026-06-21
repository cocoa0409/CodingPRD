"""The server logical clock (PRD §2.4).

A single logical clock supplies every domain timestamp the system stamps
(created_at, updated_at, admitted_at_utc, exited_at_utc, logged_at_utc) and
every "current time" comparison the rules make (reservation windows, last-call
and closing transitions, ID expiry, age computation).

At server startup the clock reads exactly 2026-01-01T00:00:00Z and stays there
until explicitly set; it never falls back to wall-clock time.
"""
import datetime

DEFAULT_CLOCK = "2026-01-01T00:00:00Z"


def parse_iso(s):
    """Parse an ISO 8601 UTC timestamp into an aware datetime (UTC)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    raw = s.strip()
    txt = raw
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return dt


def format_iso_ms(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Clock:
    def __init__(self):
        self._now = parse_iso(DEFAULT_CLOCK)

    def reset(self):
        self._now = parse_iso(DEFAULT_CLOCK)

    def now(self):
        """Current logical instant as an aware UTC datetime."""
        return self._now

    def now_iso(self):
        """Current logical instant formatted with three fractional digits."""
        return format_iso_ms(self._now)

    def set(self, iso_string):
        self._now = parse_iso(iso_string)

    def today(self):
        """Date portion of the current logical clock."""
        return self._now.date()


clock = Clock()
