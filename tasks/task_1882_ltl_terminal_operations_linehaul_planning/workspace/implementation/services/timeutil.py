"""Time helpers: ISO 8601 UTC formatting/parsing and terminal-local day math."""
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def fmt_ts(dt):
    """ISO 8601 UTC timestamp. Whole-second instants (the norm for this
    logical-clock API) render as 2026-08-01T00:00:00Z; a fractional part is
    appended with three digits only when non-zero. Returns None for None."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        return base + ".{:03d}Z".format(dt.microsecond // 1000)
    return base + "Z"


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Raises ValueError on anything unparseable. A naive value (no offset) is
    treated as UTC.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    else:
        raise ValueError("not an ISO 8601 string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date. Raises ValueError otherwise."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError("not a YYYY-MM-DD date")
    return date.fromisoformat(value)


def committed_delivery_utc(tendered_utc, dest_timezone_name, service_days):
    """tendered_at_utc + N terminal-local calendar days at the destination
    terminal, converted back to a UTC instant."""
    tz = ZoneInfo(dest_timezone_name)
    local = tendered_utc.astimezone(tz)
    committed_local = local + timedelta(days=service_days)
    return committed_local.astimezone(timezone.utc)


def day_window_utc(tz_name, report_date):
    """Half-open UTC window [local day start, next local day start) for the
    terminal-local calendar date in the given IANA timezone."""
    tz = ZoneInfo(tz_name)
    d = parse_date(report_date)
    start_local = datetime.combine(d, time(0, 0, 0), tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
