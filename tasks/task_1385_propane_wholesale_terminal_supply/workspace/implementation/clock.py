"""Server-owned logical clock. Default: exactly 2026-08-01T00:00:00Z.

The wall clock is never consulted for business time. `api_now()` (used for the
response meta timestamp and request ids) is the only wall-clock consumer.
"""
from datetime import datetime, timezone

_DEFAULT = "2026-08-01T00:00:00Z"

_state = {"current": _DEFAULT}


def _parse(ts):
    s = str(ts).strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def now():
    """Current logical instant (aware datetime, UTC)."""
    return _parse(_state["current"]).astimezone(timezone.utc)


def now_iso():
    return _state["current"]


def today_date():
    return now().date()


def set_to(iso_str):
    # Validate parseability, then store verbatim-normalized.
    dt = _parse(iso_str).astimezone(timezone.utc)
    _state["current"] = _format(dt)
    return _state["current"]


def _format(dt):
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        # truncate to milliseconds (regex allows at most 3 fractional digits)
        s = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
    else:
        s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return s + "Z"
