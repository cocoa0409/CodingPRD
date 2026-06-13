"""Server clock. Defaults to real UTC; settable via /_clock/set_current_utc."""
from datetime import datetime, timezone

_override = None  # datetime (tz-aware UTC) or None


def now():
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def set_now(dt):
    global _override
    _override = dt


def iso_now():
    return format_dt(now())


def format_dt(dt):
    """ISO 8601 UTC with three fractional digits and trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
