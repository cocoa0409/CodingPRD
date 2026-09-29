"""ISO 8601 UTC instant arithmetic used to build requests and expectations.

The logical clock advances only when a test moves it, and every instant the API
accepts or reports is an ISO 8601 UTC instant, so tests express times as
offsets from a known anchor rather than as opaque literals.
"""

from datetime import datetime, timedelta, timezone

from .constants import CLOCK_START, SECONDS_PER_DAY


def parse(instant: str) -> datetime:
    """Parse an ISO 8601 UTC instant, accepting either a trailing Z or +00:00."""
    text = instant.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def render(moment: datetime) -> str:
    """Render a datetime as an ISO 8601 UTC instant with a trailing Z."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift(
    instant: str,
    days: int = 0,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
) -> str:
    """Return ``instant`` moved by the supplied offset."""
    moved = parse(instant) + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds
    )
    return render(moved)


def at(days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0) -> str:
    """Return an instant offset from the clock's starting value."""
    return shift(CLOCK_START, days=days, hours=hours, minutes=minutes, seconds=seconds)


def elapsed_days(start: str, end: str) -> int:
    """Whole elapsed days between two instants, truncated toward zero."""
    delta = parse(end) - parse(start)
    return int(delta.total_seconds() // SECONDS_PER_DAY)


def same_instant(left: str, right: str) -> bool:
    """True when two ISO 8601 renderings denote the same instant."""
    return parse(left) == parse(right)
