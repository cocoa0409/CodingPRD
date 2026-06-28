"""ISO 8601 UTC timestamp formatting/parsing with three fractional digits."""
from datetime import datetime, timezone


def to_iso(dt):
    """Format a datetime as ISO 8601 UTC with millisecond precision and Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # Millisecond precision (three fractional digits) + Z.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp into an aware UTC datetime, or raise ValueError."""
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    raw = s.strip()
    txt = raw
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
