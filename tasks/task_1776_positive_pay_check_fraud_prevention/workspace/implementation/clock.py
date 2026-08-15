"""Logical server clock (PRD §2.5). Wall-clock time is never consulted.

Startup default is exactly 2026-08-01T00:00:00Z. The clock endpoint echoes the
caller's literal string as `current_utc`; every server-generated timestamp is
rendered from the logical instant.
"""
from datetime import datetime, timezone

UTC = timezone.utc

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

_instant = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
_literal = DEFAULT_CLOCK_UTC


def now():
    return _instant


def today():
    return _instant.date()


def literal():
    return _literal


def set_current(dt, literal_str):
    global _instant, _literal
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    _instant = dt.astimezone(UTC)
    _literal = literal_str
