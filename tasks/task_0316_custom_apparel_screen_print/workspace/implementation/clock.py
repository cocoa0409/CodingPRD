"""Datetime helpers (PRD §2.4, §2.6, §2.7).

Timestamps are ISO 8601 UTC with three fractional digits. The shop's logical
clock (`current_utc`) is stored per-Shop record (PRD §2.7), not globally; these
helpers only parse and format instants.
"""
from datetime import datetime, timezone


EPOCH_ISO = "1970-01-01T00:00:00.000Z"


def parse_iso8601(value):
    """Parse an ISO 8601 string to an aware UTC datetime, or return None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_iso8601_millis(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_real_iso():
    """Real wall-clock UTC, used only for server-minted created_at/updated_at."""
    return to_iso8601_millis(datetime.now(timezone.utc))
