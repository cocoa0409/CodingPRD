"""Logical-clock time parsing and comparison helpers.

The platform uses a logical clock (PRD §2.9) expressed as ISO 8601 UTC strings.
We parse those strings into aware datetimes purely so we can compare instants
(scheduled publishes, subscription period boundaries, grace windows). We never
read wall-clock time for business logic.
"""

from datetime import datetime, timezone, timedelta


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Accepts a trailing 'Z' as well as explicit offsets and fractional seconds.
    Returns None if value is None; raises ValueError on a malformed string.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_ms(dt, ms):
    return dt + timedelta(milliseconds=ms)


def format_iso_ms(dt):
    """Format an aware UTC datetime as ISO 8601 UTC with exactly three fractional
    digits (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_iso_ms():
    """Current logical-clock instant normalized to 3 fractional digits.

    PRD §2.9: "Time on the platform is a logical clock rather than wall-clock
    time." Resource system timestamps (created_at/updated_at, §2.4) record platform
    time and are therefore derived from the logical clock, never the host wall clock.
    """
    import db  # local import to avoid import cycle
    return format_iso_ms(parse_iso(db.db.clock))
