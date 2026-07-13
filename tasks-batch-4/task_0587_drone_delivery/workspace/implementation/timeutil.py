"""ISO 8601 UTC handling (PRD 2.5): three fractional digits, trailing Z."""
from datetime import datetime, timedelta, timezone


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def compact14(dt):
    """created_at compacted to YYYYMMDDHHMMSS (auth_code minting, PRD 3.5)."""
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


def parse(value):
    """Parse an ISO 8601 timestamp, returning an aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
