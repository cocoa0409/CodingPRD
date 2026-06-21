"""Server logical clock. Test-drivable via /_clock/set."""
from datetime import datetime, timezone

# When set (via /_clock/set), now() returns this fixed instant. Otherwise real UTC.
_fixed_now = None


def set_now(dt):
    global _fixed_now
    _fixed_now = dt


def now():
    if _fixed_now is not None:
        return _fixed_now
    return datetime.now(timezone.utc)


def iso_millis(dt=None):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        dt = now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
