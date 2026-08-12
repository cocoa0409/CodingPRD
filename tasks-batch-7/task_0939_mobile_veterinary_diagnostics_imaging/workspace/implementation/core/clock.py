"""The logical clock plus THE single instant-rendering function.

TIMESTAMP POLICY (one function, three cases — PRD 2.4 / 2.5):

  (i)   Server-minted instants (created_at, updated_at, acquired_at, published_at,
        arrived_at, performed_at, the envelope's api_request_timestamp, ...) are
        produced by `now()` (the logical clock) and rendered by `render()` as
        ISO 8601 UTC with EXACTLY three fractional digits and a trailing `Z`.

  (ii)  Caller-supplied instant strings (contract valid_from / valid_until,
        equipment calibration_valid_from / calibration_valid_until, the clock's
        `to_iso8601`) are PARSED to an aware datetime, stored as a datetime, and
        RE-RENDERED through the very same `render()`.  We consistently
        re-render rather than echo byte-verbatim; PRD 2.4 authorises exactly this
        ("a client-supplied value that carries a different textual form denotes
        the same moment and must compare equal to it").  Applied everywhere,
        without exception.

  (iii) Derived instants (tat_anchor_at, tat_deadline_at) are datetimes computed
        from (i)/(ii) values and rendered by the same `render()`.

  Plain calendar dates (Route.service_date, Invoice.period_start/period_end) are
  NOT instants: they are `YYYY-MM-DD` strings echoed back verbatim.

  There is exactly one renderer in this codebase and NOTHING calls
  `datetime.strftime`/`isoformat` for an API field outside it.  Real wall-clock
  time is never consulted anywhere in the server.
"""

from datetime import datetime, timedelta, timezone

_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _DEFAULT}


def reset():
    _state["now"] = _DEFAULT


def now():
    """The logical clock's current value as an aware UTC datetime."""
    return _state["now"]


def set_now(dt):
    _state["now"] = to_utc(dt)
    return _state["now"]


def to_utc(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render(dt):
    """THE renderer.  Aware/naive datetime -> 'YYYY-MM-DDTHH:MM:SS.mmmZ'."""
    if dt is None:
        return None
    dt = to_utc(dt)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse a client-supplied ISO-8601 instant.  Returns None when unparseable."""
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
    return to_utc(dt)


def parse_date(value):
    """Parse a plain YYYY-MM-DD calendar date.  Returns a date or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def date_utc(dt):
    return to_utc(dt).date()


def midnight_utc(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def plus_minutes(dt, minutes):
    return to_utc(dt) + timedelta(minutes=minutes)


def plus_days(dt, days):
    return to_utc(dt) + timedelta(days=days)
