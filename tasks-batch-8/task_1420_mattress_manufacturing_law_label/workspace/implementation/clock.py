"""Logical clock for the plant. Default before any set: 2026-08-01T00:00:00Z.

The server never falls back to wall-clock time.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

_current = None


def now():
    if _current is None:
        return _parse(DEFAULT_CLOCK_ISO)
    return _current


def now_iso():
    return iso_fmt(now())


def set_to(dt):
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)


def _parse(s):
    if not isinstance(s, str):
        raise ValueError("not an iso string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_parse(s):
    return _parse(s)


def try_parse(s):
    try:
        return _parse(s)
    except Exception:
        return None


def iso_fmt(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms
