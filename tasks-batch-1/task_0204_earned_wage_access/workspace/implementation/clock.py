"""Deterministic test clock.

PRD §3.12: a PlatformAdmin may pin the server clock via POST /_clock/set_current_utc
supplying a `to_iso8601` instant. Once set, that instant governs all subsequently
server-stamped fields and every elapsed-time check until it is changed again.

When unset, the clock falls back to real UTC.
"""
from datetime import datetime, timezone

from timeutil import parse_iso8601

_pinned = None  # datetime (aware, UTC) or None


def set_clock(iso_str):
    global _pinned
    _pinned = parse_iso8601(iso_str)


def now():
    """Return the current server time as an aware UTC datetime."""
    if _pinned is not None:
        return _pinned
    return datetime.now(timezone.utc)


def reset():
    global _pinned
    _pinned = None
