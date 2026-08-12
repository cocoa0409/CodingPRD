"""Logical clock (PRD §2.5).

Startup default is exactly 2026-05-01T00:00:00Z and never falls back to
wall-clock time. AuthorizerAdmin may advance it via POST
/authorizer/_clock/set_current_utc.
"""
from datetime import datetime, timezone


_DEFAULT_ISO = "2026-05-01T00:00:00Z"


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._now = _parse_iso(_DEFAULT_ISO)

    def now(self) -> datetime:
        return self._now

    def set(self, value: str) -> datetime:
        self._now = _parse_iso(value)
        return self._now


# Module-level singleton; per-boot state (no persistence).
CLOCK = LogicalClock()


def now_dt() -> datetime:
    return CLOCK.now()


def now_iso() -> str:
    """Current logical time as ISO 8601 UTC with three fractional digits."""
    return to_iso(CLOCK.now())


def to_iso(dt: datetime) -> str:
    """Format an aware UTC datetime as ISO 8601 with exactly 3 fractional
    digits and a trailing Z (PRD §2.4 / §2.2)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{dt.microsecond // 1000:03d}"
    return f"{base}.{millis}Z"


def parse(value: str) -> datetime:
    return _parse_iso(value)


def iso_date_year(value: str) -> int:
    """Year component of an ISO date/datetime string."""
    return _parse_iso(value).year
