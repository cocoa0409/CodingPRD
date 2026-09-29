"""ISO 8601 UTC timestamps with three fractional digits (PRD §2.4)."""

from datetime import datetime, timedelta, timezone

# Before any client sets it, the logical clock reads exactly this instant and it
# never falls back to real wall-clock time.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00.000Z"


def parse_iso(text):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_iso(moment):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if moment is None:
        return None
    moment = moment.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year,
        moment.month,
        moment.day,
        moment.hour,
        moment.minute,
        moment.second,
        moment.microsecond // 1000,
    )


def add_days(moment, days):
    """Deadlines expressed in days add that whole number of days."""
    return moment + timedelta(days=int(days))


def add_days_iso(iso_text, days):
    return fmt_iso(add_days(parse_iso(iso_text), days))


def month_start_iso(year, month, day):
    return fmt_iso(datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc))


def real_now_iso():
    return fmt_iso(datetime.now(timezone.utc))


def cmp_iso(left, right):
    """-1/0/1 comparison of two ISO instants (None sorts last)."""
    a = parse_iso(left)
    b = parse_iso(right)
    if a is None and b is None:
        return 0
    if a is None:
        return 1
    if b is None:
        return -1
    if a < b:
        return -1
    if a > b:
        return 1
    return 0
