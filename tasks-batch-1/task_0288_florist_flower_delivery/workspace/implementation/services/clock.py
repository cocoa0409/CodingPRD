"""Simulated wall clock (PRD §2.10). Same-day cutoff and surge-window
membership read this clock, not real time."""
from datetime import datetime, timezone, timedelta

import errors
from db import store


def _parse_iso(value):
    """Parse an ISO 8601 instant. Accepts a trailing 'Z' or an explicit offset.
    Returns a timezone-aware datetime in UTC."""
    if not isinstance(value, str) or value.strip() == "":
        raise errors.invalid_request("to_iso8601 must be a non-empty ISO 8601 string")
    raw = value.strip()
    try:
        s = raw
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request("to_iso8601 is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def set_clock(value):
    dt = _parse_iso(value)
    store.clock["current_utc"] = dt.strftime("%Y-%m-%dT%H:%M:%S.") + \
        ("%03d" % (dt.microsecond // 1000)) + "Z"
    return dt


def current_dt():
    """Return the current simulated clock as a UTC datetime, or None if unset."""
    cur = store.clock.get("current_utc")
    if cur is None:
        return None
    return _parse_iso(cur)


def clock_date():
    """Calendar date (YYYY-MM-DD) of current_utc, or None if unset."""
    dt = current_dt()
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d")


def clock_hour():
    """UTC hour-of-day of current_utc, or None if unset."""
    dt = current_dt()
    if dt is None:
        return None
    return dt.hour


def parse_date(value):
    """Parse a YYYY-MM-DD string into a date; raise ERR_INVALID_REQUEST if bad."""
    if not isinstance(value, str):
        raise errors.invalid_request("date must be a YYYY-MM-DD string")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise errors.invalid_request("date must be a valid YYYY-MM-DD calendar date")


def add_days(date_str, days):
    d = parse_date(date_str)
    return (d + timedelta(days=days)).strftime("%Y-%m-%d")


def add_one_month(date_str):
    """Advance by one calendar month, clamping the day to the month's length."""
    d = parse_date(date_str)
    month = d.month + 1
    year = d.year
    if month > 12:
        month = 1
        year += 1
    # Clamp day to last valid day of the target month.
    day = d.day
    while True:
        try:
            return d.replace(year=year, month=month, day=day).strftime("%Y-%m-%d")
        except ValueError:
            day -= 1
            if day < 1:
                raise
