"""Instant parsing, instant RENDERING and calendar arithmetic.

G2 -- TIMESTAMP RENDERING, ADJUDICATED ONCE AND ENFORCED BY CONSTRUCTION.

  * ``render_instant`` is the ONE and ONLY function in the whole service that
    turns a datetime into a string that leaves the server.  Every
    server-minted instant (created_at, updated_at, api_request_timestamp,
    suspended_at, activated_at, activation_expires_at, first_response_at,
    resolved_at, closed_at, pause_started_at, survey_solicited_at, started_at,
    ended_at, cancelled_at, result_reported_at, shipped_at, returned_at,
    submitted_at, cycle_start_at, cycle_end_at, warranty_expires_at,
    return_deadline_at, window_closes_at) is produced by it, so they all carry
    exactly three fractional digits and a trailing ``Z`` -- PRD 2.4.

  * Instants DERIVED from a server-minted instant (return_deadline_at =
    shipped_at + 14 days, window_closes_at = survey_solicited_at + 72 hours,
    cycle_end_at = cycle_start_at + 30 days, activation_expires_at = clock +
    1440 minutes) are also server-minted and therefore also carry the
    server style.  There is no second style in the codebase.

  * Caller-supplied instant STRINGS are echoed back verbatim, byte for byte,
    because the PRD says those fields store what the caller sent:
    VisitSlot.start_at / end_at (PRD 3.8 "supplying start_at and end_at"),
    FirmwareCampaign.ring_window_start_at / ring_window_end_at ("set to the
    requested window"), FirmwareRollout.window_start_at / window_end_at
    ("copied from the campaign's ring window"), FirmwareRollout.deferred_until
    ("set to the requested instant"), Device.purchase_date (a YYYY-MM-DD date
    string), and the clock's ``current_utc`` ("carrying the clock's new
    value", i.e. the instant the caller supplied).

  * Instants copied from a caller-supplied string keep that same string
    unchanged: Visit.scheduled_start_at / scheduled_end_at are "copied from
    the occupied slot" and are therefore the slot's verbatim strings.

  Nothing anywhere re-renders a caller string, and nothing anywhere emits a
  server instant in any other style.
"""

import calendar
from datetime import datetime, timedelta, timezone

from errors import ApiError

UTC = timezone.utc


# --------------------------------------------------------------------------
# The single renderer
# --------------------------------------------------------------------------
def render_instant(dt):
    """The ONE renderer for every server-minted instant: ISO 8601 UTC, three
    fractional digits, trailing 'Z' (PRD 2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------
def try_parse_instant(value):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    txt = raw
    if txt.endswith("z") or txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_instant(value, error_id="ERR_INVALID_REQUEST"):
    dt = try_parse_instant(value)
    if dt is None:
        raise ApiError(error_id)
    return dt


def try_parse_date(value):
    """Parse a YYYY-MM-DD calendar date into a (year, month, day) tuple."""
    if not isinstance(value, str) or len(value) != 10:
        return None
    if value[4] != "-" or value[7] != "-":
        return None
    try:
        y, m, d = int(value[0:4]), int(value[5:7]), int(value[8:10])
        datetime(y, m, d)
    except ValueError:
        return None
    return (y, m, d)


# --------------------------------------------------------------------------
# Arithmetic
# --------------------------------------------------------------------------
def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_months_to_date(ymd, months):
    """Add whole months to a (y, m, d) date, clamping to the last day of the
    target month when that month has no such day-of-month (PRD 3.3)."""
    y, m, d = ymd
    total = (y * 12) + (m - 1) + months
    ny, nm = divmod(total, 12)
    nm += 1
    last = calendar.monthrange(ny, nm)[1]
    return (ny, nm, min(d, last))


def midnight_utc(ymd):
    return datetime(ymd[0], ymd[1], ymd[2], 0, 0, 0, tzinfo=UTC)


def floor_minutes_between(a, b):
    """Whole minutes from a to b by floor division on a 60-second minute."""
    return int((b - a).total_seconds()) // 60


def floor_days_between(a, b):
    """Whole days from a to b by floor division on an 86 400-second day."""
    return int((b - a).total_seconds()) // 86400
