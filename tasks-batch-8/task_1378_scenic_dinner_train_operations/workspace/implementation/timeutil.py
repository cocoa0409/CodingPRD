"""ISO8601 UTC helpers. All logical-clock values are stored as ISO strings with
three fractional digits and a Z suffix; dates are strict YYYY-MM-DD."""
import re
from datetime import date, datetime, timezone

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso(value):
    """Parse an ISO8601 datetime string into an aware UTC datetime. Raises ValueError."""
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


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date. Raises ValueError."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError("not an ISO date")
    return date.fromisoformat(value)


def iso_z(dt):
    """Format an aware datetime as ISO8601 UTC with exactly 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
