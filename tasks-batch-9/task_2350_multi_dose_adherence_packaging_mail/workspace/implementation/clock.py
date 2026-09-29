"""The settable logical clock (PRD 2.4).

Default reading until the setter endpoint is first called:
``2026-08-01T00:00:00Z``.  Module level state is fresh on every process boot,
which is exactly what the ``--isolation per-test-server`` harness wants.
"""

from datetime import datetime, timedelta, timezone

DEFAULT_CURRENT_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"current_utc": DEFAULT_CURRENT_UTC}


def now():
    """The current logical-clock instant (timezone-aware, UTC)."""
    return _state["current_utc"]


def today():
    """The clock date: the logical instant's UTC calendar date."""
    return _state["current_utc"].date()


def set_now(value):
    _state["current_utc"] = value.astimezone(timezone.utc)
    return _state["current_utc"]


def fmt_instant(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2/2.5)."""
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def now_iso():
    return fmt_instant(now())


def wall_iso():
    return fmt_instant(datetime.now(timezone.utc))


def plus_hours(value, hours):
    return value + timedelta(hours=hours)


def hours_from_now_iso(hours):
    """The clock advanced by whole hours, formatted canonically."""
    return fmt_instant(plus_hours(now(), hours))
