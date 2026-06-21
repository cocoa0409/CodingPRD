"""Server clock. Defaults to real UTC now, overridable by the test-driving
clock endpoint (PRD §3.1)."""
from datetime import datetime, timezone

_override = None  # datetime in UTC, or None to use real clock


def set_now(dt):
    global _override
    _override = dt


def now():
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def now_iso():
    """ISO 8601 UTC with exactly three fractional digits, 'Z' suffix."""
    return fmt_iso(now())


def fmt_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # milliseconds, three fractional digits
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def reset():
    global _override
    _override = None
