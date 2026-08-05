"""Timestamp handling.

TIMESTAMP RENDERING RULE (single, global, applied everywhere):

  * A caller-supplied datetime string is echoed back **verbatim**, byte for byte,
    exactly as it arrived on the wire.  (booked_at, prior_full_assessment_at,
    scheduled_release_date, start_date, end_date, scheduled_at, appointment_at,
    grieved_event_at, planned_release_at, death_at, ...)
  * Every **server-generated** stamp -- anything minted from the logical clock or
    at row creation (created_at, updated_at, submitted_at, triaged_at, seen_at,
    enrolled_at, recorded_at, acted_at, opened_at, decided_at, requested_at,
    authorized_at, stage_entered_at, completed_at, closed_at, api_request_timestamp)
    -- is rendered in ONE canonical format: ISO 8601 UTC with exactly three
    fractional digits, `YYYY-MM-DDTHH:MM:SS.mmmZ`.  (PRD 2.4)
  * Every **derived** instant (an anchor plus a whole number of hours or days:
    due_at, next_due_date, response_deadline_at, deadline_anchor_at,
    turnaround_deadline_at, response_due_at, due_at_snapshot ...) is likewise
    rendered in the canonical three-fractional-digit format, per PRD 2.8:
    "Timestamps computed by adding a whole number of hours or days to an anchor
    are whole-second instants and are serialized as ISO 8601 UTC with three
    fractional digits, which for such computed deadlines are always `.000`."
"""

from datetime import datetime, timedelta, timezone


class Ts:
    """An instant plus the exact string that should be echoed for it."""

    __slots__ = ("dt", "s")

    def __init__(self, dt, s):
        self.dt = dt
        self.s = s

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Ts(%s)" % self.s


def canonical(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def mint(dt):
    """Server-generated / derived instant -> canonical rendering."""
    return Ts(dt, canonical(dt))


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def verbatim(value):
    """Caller-supplied datetime string -> Ts echoing the original text."""
    dt = parse_dt(value)
    if dt is None:
        return None
    return Ts(dt, value)


def out(ts):
    return ts.s if isinstance(ts, Ts) else ts


def add_hours(ts, hours):
    return mint(ts.dt + timedelta(hours=hours))


def add_days(ts, days):
    return mint(ts.dt + timedelta(days=days))


def floor_minutes(later, earlier):
    """Signed whole minutes between two instants, floored toward -infinity."""
    seconds = (later - earlier).total_seconds()
    return int(seconds // 60)


def day_diff(later_date, earlier_date):
    return (later_date - earlier_date).days
