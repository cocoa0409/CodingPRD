"""ISO 8601 UTC parsing and formatting.

PRD 2.4: every server-stamped timestamp is an ISO 8601 UTC instant rendered with
exactly three fractional digits and a trailing ``Z``.
"""

from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def wall_now():
    """Real wall-clock instant. Used only for the envelope's
    api_request_timestamp (PRD 2.2); every resource timestamp the server stamps
    is read from the logical assessment clock of PRD 2.5 instead."""
    return datetime.now(UTC)


def fmt_iso(value):
    """Render a datetime as ``YYYY-MM-DDTHH:MM:SS.mmmZ`` (three fractional digits)."""
    if value is None:
        return None
    if not isinstance(value, datetime):
        return value
    dt = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 UTC instant. Returns ``None`` when unparseable."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def plus_days(moment, days):
    return moment + timedelta(days=days)


def plus_minutes(moment, minutes):
    return moment + timedelta(minutes=minutes)
