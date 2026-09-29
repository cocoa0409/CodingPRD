"""ISO-8601 UTC formatting / parsing helpers.

Every instant the API emits is rendered with exactly three fractional digits
and a trailing Z.  Every instant the API accepts is normalised to UTC.
"""

from datetime import datetime, date, timedelta, timezone

from errors import ApiError


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def parse_instant(value, error_id="ERR_INVALID_REQUEST"):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(error_id, "A valid ISO 8601 UTC instant is required.")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        raise ApiError(error_id, "A valid ISO 8601 UTC instant is required.")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_business_date(value, error_id="ERR_INVALID_REQUEST"):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(error_id, "A valid YYYY-MM-DD business date is required.")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise ApiError(error_id, "A valid YYYY-MM-DD business date is required.")


def date_str(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def utc_date(dt):
    return dt.astimezone(timezone.utc).date()


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)
