"""Logical clock. Startup default fixed at 2026-04-01T00:00:00Z.

Never falls back to wall-clock time. All now() reads use the logical value.
"""
from datetime import datetime, timezone

# Fixed startup default per PRD §2.10.
_DEFAULT = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = _DEFAULT


def reset():
    global _current
    _current = _DEFAULT


def set_now(dt: datetime):
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)


def now() -> datetime:
    return _current


def now_iso() -> str:
    """ISO 8601 UTC with exactly three fractional digits, trailing Z."""
    dt = _current.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
