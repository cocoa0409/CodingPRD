"""ISO 8601 UTC timestamp parsing and formatting (three fractional digits)."""

from datetime import datetime, timezone


def now_iso():
    """Server wall-clock now as ISO 8601 UTC with milliseconds and Z suffix.

    Used only for created_at/updated_at and the response envelope timestamp.
    Domain time always reads the deterministic arena clock instead.
    """
    return format_iso(datetime.now(timezone.utc))


def format_iso(dt):
    """Render a tz-aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
EPOCH_ISO = format_iso(EPOCH)


def parse_iso(value):
    """Parse an ISO 8601 timestamp into a tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive values are treated as
    UTC. Returns None when the value is not a parseable string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def full_years_between(dob, ref):
    """Full integer years from dob to ref (age at ref instant)."""
    years = ref.year - dob.year
    # Subtract one if the anniversary has not yet occurred this year.
    if (ref.month, ref.day, ref.hour, ref.minute, ref.second, ref.microsecond) < (
        dob.month,
        dob.day,
        dob.hour,
        dob.minute,
        dob.second,
        dob.microsecond,
    ):
        years -= 1
    return years
