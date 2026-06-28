"""Datetime parsing for ISO 8601 UTC instants (reservations, clock)."""
import datetime

from errors import validation


def parse_iso(value, err=None):
    """Parse an ISO 8601 UTC string into an aware datetime.
    Raises the supplied error factory on a malformed value."""
    if not isinstance(value, str):
        raise (err() if err else validation("Invalid datetime"))
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.datetime.fromisoformat(s2)
    except (ValueError, TypeError):
        raise (err() if err else validation("Invalid datetime"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)
