"""Time helpers for the logical clock (PRD §3.9). All instants are tz-aware UTC."""
from datetime import datetime, timezone


def parse_iso(s):
    """Parse an ISO 8601 instant (accepts trailing Z) to a tz-aware UTC datetime."""
    if isinstance(s, datetime):
        dt = s
    else:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Render a tz-aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
