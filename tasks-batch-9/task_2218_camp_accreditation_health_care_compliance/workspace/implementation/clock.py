"""The logical clock (PRD 2.4).

Time in this domain is never wall-clock time.  Before any client sets it the
clock reads exactly 2026-08-01T00:00:00Z and the server never falls back to
real time.
"""

from datetime import datetime, timedelta, timezone

INITIAL = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": INITIAL}


def now_dt():
    return _state["now"]


def set_now(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _state["now"] = dt.astimezone(timezone.utc)
    return _state["now"]


def reset():
    _state["now"] = INITIAL


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(now_dt())


def today():
    return now_dt().date()


def date_str(d):
    return d.isoformat() if d is not None else None


def plus_days(d, days):
    return d + timedelta(days=days)


def end_of_day_iso(d):
    return "%sT23:59:59.999Z" % d.isoformat()
