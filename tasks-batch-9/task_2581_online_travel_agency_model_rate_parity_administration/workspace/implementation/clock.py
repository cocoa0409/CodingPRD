"""Server-held logical UTC clock (PRD §2.5). Nothing here reads the host clock
for domain reasoning; only the response envelope timestamp uses wall time."""
import datetime as _dt

UTC = _dt.timezone.utc
DEFAULT_INSTANT = _dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_state = {"now": DEFAULT_INSTANT}


def reset():
    _state["now"] = DEFAULT_INSTANT


def now():
    """Current logical instant (aware datetime, UTC)."""
    return _state["now"]


def set_now(instant):
    _state["now"] = instant


def today():
    """Current logical calendar date."""
    return _state["now"].date()


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso(dt):
    """ISO 8601 UTC; fractional part only when non-zero."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso_ms():
    return iso_ms(_state["now"])


def now_iso():
    return iso(_state["now"])


def parse_instant(text):
    """Parse an ISO 8601 UTC instant. Returns None when unparseable."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_date(text):
    """Parse a YYYY-MM-DD calendar date. Returns None when unparseable."""
    if not isinstance(text, str) or len(text) != 10:
        return None
    try:
        return _dt.date.fromisoformat(text)
    except ValueError:
        return None


def plus_days(dt, days):
    return dt + _dt.timedelta(days=days)


def date_at_hour(day, hour):
    """Calendar date at a fixed UTC hour (ARRIVAL_HOUR_UTC)."""
    return _dt.datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=UTC)


OPEN_ENDED_DATE = _dt.date(9999, 12, 31)
