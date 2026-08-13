"""Date / datetime parsing helpers."""
import re
from datetime import datetime, timezone

UTC = timezone.utc
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_date_str(s):
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def is_dt_str(s):
    if not isinstance(s, str):
        return False
    try:
        parse_dt(s)
        return True
    except (ValueError, TypeError):
        return False


def parse_dt(s):
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
