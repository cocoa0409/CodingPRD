"""ISO 8601 datetime parsing and formatting helpers."""

from datetime import datetime, timezone, timedelta

from errors import ERR_BAD_REQUEST, raise_error


def parse_iso8601(value, field_name):
    """Parse an ISO 8601 string into a timezone-aware datetime (UTC)."""
    if not isinstance(value, str):
        raise_error(ERR_BAD_REQUEST, f"Field {field_name} must be ISO 8601 string")
    s = value.strip()
    # Accept trailing Z by converting to +00:00 for fromisoformat
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise_error(ERR_BAD_REQUEST, f"Field {field_name} is not valid ISO 8601")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_iso8601(dt):
    """Format datetime as ISO 8601 UTC with three fractional digits + Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{dt.microsecond // 1000:03d}"
    return f"{s}.{millis}Z"


def iso_week_label(dt):
    """ISO-week label, e.g., '2026-W19'."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    iso_year, iso_week, _ = dt.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def business_date_plus_minutes(business_date_dt, minutes):
    """Add minutes to business_date midnight."""
    return business_date_dt + timedelta(minutes=minutes)
