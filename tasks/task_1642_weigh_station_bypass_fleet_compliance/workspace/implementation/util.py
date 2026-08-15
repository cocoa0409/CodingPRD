"""Time/date helpers. All business time comes from the logical clock in db.py."""
import re
from datetime import date, datetime, timezone

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_datetime(s):
    """Parse an ISO-8601 datetime into an aware UTC datetime; None on failure."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith(("Z", "z")):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a strict YYYY-MM-DD date; None on failure."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        return date(int(s[0:4]), int(s[5:7]), int(s[8:10]))
    except ValueError:
        return None


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
