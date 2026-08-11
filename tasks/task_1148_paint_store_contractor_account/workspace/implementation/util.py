"""Time helpers: ISO 8601 UTC parsing/formatting against the logical clock."""
from datetime import datetime, timezone

from errors import raise_err, ERR_VALIDATION


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ERR_VALIDATION (400) on any malformed value."""
    if not isinstance(value, str) or isinstance(value, bool):
        raise_err(ERR_VALIDATION, "field '%s' must be an ISO 8601 datetime string" % field)
    text = value.strip()
    if not text:
        raise_err(ERR_VALIDATION, "field '%s' must be an ISO 8601 datetime string" % field)
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    dt = None
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        dt = None
    if dt is None:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        raise_err(ERR_VALIDATION, "field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
