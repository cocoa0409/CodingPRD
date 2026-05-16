"""Virtual logical clock — advanced by ProgramAdmin via /_clock/advance."""

from datetime import datetime, timezone

from errors import APIError


class VirtualClock:
    def __init__(self):
        # Initialize to wall-clock so tests whose fixtures derive ISO
        # timestamps from real-now have a sane baseline. PRD is silent on
        # the initial value of the logical clock — "Wall-clock time is
        # not consulted anywhere else" leaves initialization permissible.
        # The clock is monotonic forward from this baseline thereafter.
        self._now = datetime.now(tz=timezone.utc)

    def now(self):
        return self._now

    def now_iso(self):
        return format_iso(self._now)

    def advance_to(self, target_iso):
        target = parse_iso(target_iso)
        if target < self._now:
            raise APIError(
                "ERR_VALIDATION", "Clock can only move forward."
            )
        self._now = target
        return self._now

    def reset(self):
        self._now = datetime.now(tz=timezone.utc)


def format_iso(dt):
    """ISO 8601 UTC with millisecond precision and Z suffix (per PRD §2.2)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime(f"%Y-%m-%dT%H:%M:%S.{ms:03d}Z")


def parse_iso(value):
    """Parse an ISO 8601 datetime into an aware UTC datetime."""
    if not isinstance(value, str):
        raise APIError("ERR_VALIDATION", "Datetime must be an ISO 8601 string.")
    s = value.strip()
    if not s:
        raise APIError("ERR_VALIDATION", "Datetime string is empty.")
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


def parse_iso_date(value):
    """Parse an ISO 8601 calendar date (YYYY-MM-DD)."""
    if not isinstance(value, str):
        raise APIError("ERR_VALIDATION", "Date must be an ISO 8601 string.")
    s = value.strip()
    if len(s) != 10 or s[4] != "-" or s[7] != "-":
        raise APIError("ERR_VALIDATION", f"Invalid ISO date: {value}")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise APIError("ERR_VALIDATION", f"Invalid ISO date: {value}")


# Singleton
clock = VirtualClock()
