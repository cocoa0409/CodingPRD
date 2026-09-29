"""The logical clock: the single source of every 'now' in this API.

PRD 2.4 -- nothing in this system reads the wall clock. The startup default is
exactly 2026-08-01T00:00:00Z and it must never fall back to real time.
"""
from datetime import datetime, timedelta, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, 0)

_state = {"now": DEFAULT_NOW}


def parse_instant(raw):
    """Parse an ISO 8601 date or datetime into a naive UTC datetime.

    Returns None when the value cannot be understood.
    """
    if isinstance(raw, datetime):
        if raw.tzinfo is not None:
            return raw.astimezone(timezone.utc).replace(tzinfo=None)
        return raw
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # tolerate a space separator and extra fractional precision
        try:
            dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            try:
                dt = datetime.strptime(s[:10], "%Y-%m-%d")
            except ValueError:
                return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_date(raw):
    dt = parse_instant(raw)
    if dt is None:
        return None
    return dt.date()


def now():
    return _state["now"]


def today():
    return _state["now"].date()


def set_now(dt):
    _state["now"] = dt


def reset():
    _state["now"] = DEFAULT_NOW


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(_state["now"])


def date_iso(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


def plus_days(d, n):
    return d + timedelta(days=n)


def add_months(d, months):
    """Calendar-month arithmetic with clamping to the target month's last day."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last = _last_day(y, m)
    day = min(d.day, last)
    return d.replace(year=y, month=m, day=day)


def _last_day(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1)
    else:
        nxt = datetime(year, month + 1, 1)
    return (nxt - timedelta(days=1)).day


def completed_years(birth, ref):
    """Completed whole years between two dates; the anniversary itself counts."""
    years = ref.year - birth.year
    if (ref.month, ref.day) < (birth.month, birth.day):
        years -= 1
    return years
