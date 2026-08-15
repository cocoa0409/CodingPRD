"""ISO8601 UTC time helpers. All logical-clock values are stored as ISO strings
with three fractional digits and a Z suffix; parsing accepts offsets and Z."""
from datetime import datetime, timezone

MS_PER_DAY = 86400000


def parse_iso(value):
    """Parse an ISO8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not an ISO8601 string")
    text = value.strip()
    if not text:
        raise ValueError("empty timestamp")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    """Format an aware datetime as ISO8601 UTC with exactly 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def whole_days(earlier, later):
    """Whole (floored) days between two datetimes; never negative."""
    ms = int((later - earlier).total_seconds() * 1000)
    if ms <= 0:
        return 0
    return ms // MS_PER_DAY
