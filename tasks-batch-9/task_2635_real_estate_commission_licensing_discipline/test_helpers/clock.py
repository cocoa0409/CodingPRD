"""Helpers for reasoning about the logical commission clock.

The PRD's clock is a plain UTC instant that an operator moves explicitly, and
every deadline is "that instant plus N multiples of 86,400 seconds".  These
helpers reproduce exactly that arithmetic so a test can state an expected
`license_expires_at` or `remediation_due_at` without hand-computing dates.
"""

from datetime import datetime, timedelta, timezone

from .constants import CLOCK_STARTUP_DEFAULT, SECONDS_PER_DAY


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def to_instant_string(moment: datetime) -> str:
    """Render a datetime back in the PRD's `...Z` second-precision form."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def instant_plus_days(value: str, days: int) -> str:
    """`value` plus `days` multiples of 86,400 seconds, as an instant string."""
    return to_instant_string(
        parse_instant(value) + timedelta(seconds=days * SECONDS_PER_DAY)
    )


def instant_plus_seconds(value: str, seconds: int) -> str:
    return to_instant_string(parse_instant(value) + timedelta(seconds=seconds))


def instant_minus_days(value: str, days: int) -> str:
    return instant_plus_days(value, -days)


def calendar_date_of(value: str) -> str:
    """The calendar date (YYYY-MM-DD) of an instant."""
    return parse_instant(value).strftime("%Y-%m-%d")


def elapsed_days(start: str, end: str) -> int:
    """Whole days elapsed between two instants, truncated toward zero."""
    delta = parse_instant(end) - parse_instant(start)
    return int(delta.total_seconds() // SECONDS_PER_DAY)


def startup_instant() -> str:
    """The mandatory startup default of the logical clock."""
    return CLOCK_STARTUP_DEFAULT


def date_plus_days(value: str, days: int) -> str:
    """A YYYY-MM-DD date plus N days, as a YYYY-MM-DD date."""
    base = datetime.strptime(value, "%Y-%m-%d")
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")
