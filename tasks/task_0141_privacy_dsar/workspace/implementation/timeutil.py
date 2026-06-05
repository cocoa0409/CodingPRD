"""Time parsing/formatting helpers.

All timestamps in this system are ISO 8601 UTC with three fractional digits
(PRD §2.4). Operator-supplied instants (received_at, to_iso8601) may arrive with
or without fractional seconds and may use a 'Z' suffix or a +00:00 offset; we
normalise everything to an aware UTC datetime internally and serialise back out
with exactly three fractional digits.

Deadline arithmetic adds whole CALENDAR days preserving time-of-day (PRD §2.6,
§3.3); processor-ack arithmetic adds exact hours on the UTC instant (PRD §3.6).
"""

from datetime import datetime, timedelta, timezone


def now_utc():
    return datetime.now(timezone.utc)


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns None if the value is
    not a parseable ISO 8601 string. Naive inputs are assumed to be UTC.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # datetime.fromisoformat (py3.9) does not accept 'Z'; swap to +00:00.
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Serialise an aware datetime to ISO 8601 UTC with millisecond precision.

    Example: 2026-02-04T09:00:00.000Z
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    # %f yields microseconds (6 digits); truncate to milliseconds (3 digits).
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_calendar_days(dt, days):
    """Add whole calendar days, preserving time-of-day (timedelta on the UTC instant)."""
    return dt + timedelta(days=days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def business_days_remaining(current_utc, deadline_at):
    """Count business days (Mon-Fri, UTC) in the half-open window
    (date(current_utc), date(deadline_at)] — start date excluded, deadline
    date included if it is a weekday. Floors at 0 (PRD §3.3 / calc table).
    """
    if deadline_at < current_utc:
        return 0
    start_date = current_utc.date()
    end_date = deadline_at.date()
    count = 0
    d = start_date + timedelta(days=1)
    while d <= end_date:
        if d.weekday() < 5:  # Mon=0 .. Fri=4 count; Sat=5/Sun=6 excluded
            count += 1
        d += timedelta(days=1)
    return count
