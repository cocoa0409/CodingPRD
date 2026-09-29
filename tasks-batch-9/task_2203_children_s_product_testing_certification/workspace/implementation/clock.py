"""Server-held logical clock (PRD section 2.4).

Every deadline, coverage-window boundary, due date, expiry check and traceback
cutoff reads this clock and never the machine's wall time. At startup the
logical clock reads exactly 2026-08-01T00:00:00Z.
"""

from datetime import datetime, timedelta, timezone

STARTUP_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": STARTUP_UTC}


def reset():
    _state["now"] = STARTUP_UTC


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = to_utc(dt)
    return _state["now"]


def to_utc(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_millis(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = to_utc(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_instant(dt):
    """ISO 8601 UTC rendering of a domain instant.

    PRD 2.4 pins the three-fractional-digit format on `created_at` and
    `updated_at` only, and states the logical clock "reads exactly
    2026-08-01T00:00:00Z". Domain instants — the clock's own reading, the
    fields stamped from it, and the instants a client supplied — are therefore
    rendered at second precision, with a fractional part appearing only when
    the instant actually carries one.
    """
    if dt is None:
        return None
    dt = to_utc(dt)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso_millis():
    return iso_millis(now())


def now_iso_instant():
    return iso_instant(now())


def parse_iso8601(text):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return to_utc(dt)


def add_days(dt, days):
    return to_utc(dt) + timedelta(days=days)


def _last_day_of_month(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return (nxt - timedelta(days=1)).day


def add_calendar_months(dt, months):
    """Calendar-month arithmetic with day-of-month clamping (PRD calc 8).

    The day of month is preserved when the target month has that day, and
    clamped down to the target month's last day otherwise. Time of day is
    preserved exactly.
    """
    dt = to_utc(dt)
    total = (dt.year * 12 + (dt.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = min(dt.day, _last_day_of_month(year, month))
    return dt.replace(year=year, month=month, day=day)
