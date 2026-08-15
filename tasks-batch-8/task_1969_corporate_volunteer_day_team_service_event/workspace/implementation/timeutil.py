"""Datetime helpers: ISO 8601 UTC with three fractional digits for system stamps.

Input datetime fields keep their raw client-supplied string for output while a
parsed UTC-normalized datetime is kept for logic.
"""
import re
from datetime import datetime, date, timezone

from errors import raise_err, ERR_VALIDATION

_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fmt_ts(dt):
    """ISO 8601 UTC, three fractional digits, trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_datetime(value, field):
    """Parse an ISO 8601 datetime to aware UTC datetime. ERR_VALIDATION on failure."""
    if not isinstance(value, str) or not _DT_RE.match(value.strip()):
        raise_err(ERR_VALIDATION, f"{field} must be an ISO 8601 UTC datetime")
    s = value.strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # normalize offset without colon
    m = re.search(r"([+-]\d{2})(\d{2})$", s)
    if m:
        s = s[: m.start()] + m.group(1) + ":" + m.group(2)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err(ERR_VALIDATION, f"{field} must be an ISO 8601 UTC datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    """Parse an ISO 8601 date (or datetime) into a date. ERR_VALIDATION on failure."""
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, f"{field} must be an ISO 8601 date")
    s = value.strip()
    try:
        if _DATE_RE.match(s):
            return date.fromisoformat(s)
        if _DT_RE.match(s):
            return parse_datetime(s, field).date()
    except ValueError:
        pass
    raise_err(ERR_VALIDATION, f"{field} must be an ISO 8601 date")
