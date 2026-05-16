"""Virtual clock — advanced by PlatformAdmin via /tutoring/_clock/advance."""

from datetime import datetime, timezone

from errors import APIError


class VirtualClock:
    def __init__(self):
        # Initialize to a fixed epoch so that all timestamps are deterministic
        # and well-known relative offsets work in tests. Tests advance via API.
        self._now = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def now_iso(self):
        return format_iso(self._now)

    def advance_to(self, target_iso):
        target = parse_iso(target_iso)
        if target < self._now:
            raise APIError(
                "ERR_VALIDATION",
                "Clock can only move forward.",
            )
        self._now = target
        return self._now


def format_iso(dt):
    """Format datetime as ISO 8601 UTC with millisecond precision and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Format with millisecond precision
    ms = dt.microsecond // 1000
    return dt.strftime(f"%Y-%m-%dT%H:%M:%S.{ms:03d}Z")


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise APIError("ERR_VALIDATION", "Datetime must be an ISO 8601 string.")
    s = value.strip()
    if not s:
        raise APIError("ERR_VALIDATION", "Datetime string is empty.")
    # Normalize trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise APIError("ERR_VALIDATION", f"Invalid ISO 8601 datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


# Singleton
clock = VirtualClock()
