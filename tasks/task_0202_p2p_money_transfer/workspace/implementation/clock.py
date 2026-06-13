"""Server clock. Defaults to real UTC; PlatformAdmin can pin it via /_clock/set_current_utc.

State lives in the in-memory db so per-process reboot resets it.
"""
from datetime import datetime, timezone


def parse_iso8601(s):
    """Parse an ISO 8601 string (accepting a trailing 'Z') into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso8601(dt):
    """ISO 8601 UTC with exactly three fractional digits and a 'Z' suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
