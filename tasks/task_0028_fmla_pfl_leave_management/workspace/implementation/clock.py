"""Logical clock — overridable for deterministic test driving."""
from datetime import datetime, timezone


_now_override = None  # datetime in UTC, or None


def now_utc():
    """Return the logical now() — overridden clock if set, else wall clock UTC."""
    if _now_override is not None:
        return _now_override
    return datetime.now(timezone.utc)


def set_now(dt):
    global _now_override
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    _now_override = dt


def iso8601_ms(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # microseconds -> milliseconds: 3 digit fractional
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_iso8601(s):
    """Parse an ISO 8601 string into an aware UTC datetime."""
    if s is None:
        return None
    if not isinstance(s, str):
        raise ValueError("expected string for datetime")
    # Accept trailing Z or explicit offset.
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError as exc:
        raise ValueError(f"invalid ISO 8601 datetime: {s!r}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
