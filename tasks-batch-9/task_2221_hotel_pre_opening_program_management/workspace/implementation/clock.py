"""Server-side logical clock (PRD §2.4).

Before any client sets it the logical clock reads exactly 2026-08-01T00:00:00Z
and it never falls back to real wall-clock time.
"""
from datetime import datetime, timezone, date

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_CLOCK}


def reset():
    _state["now"] = DEFAULT_CLOCK


def now():
    """Current logical instant (aware, UTC)."""
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)
    return _state["now"]


def today():
    """Current logical calendar date."""
    return _state["now"].date()


def wall_now():
    """Real wall clock -- used only for created_at / updated_at / meta stamps."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Formatting / parsing helpers
# ---------------------------------------------------------------------------

def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


def parse_date_strict(value):
    """Parse YYYY-MM-DD. Returns a date or None when unparseable."""
    if not isinstance(value, str):
        return None
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except (ValueError, TypeError):
        return None


def parse_instant(value):
    """Parse a permissive ISO 8601 instant. Returns aware UTC datetime or None."""
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
