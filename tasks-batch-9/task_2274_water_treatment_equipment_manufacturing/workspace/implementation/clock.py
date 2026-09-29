"""Logical clock.

Every temporal comparison and every ``*_at`` stamp the server writes reads
"now" from here, never from the wall clock.  Seeded at 2026-08-01T00:00:00Z on
each fresh boot and only ever moved by POST /_clock/set_current_utc.
"""
from util import format_dt, parse_dt

SEED = "2026-08-01T00:00:00.000Z"

_now = parse_dt(SEED)


def now():
    """Current logical instant as an aware datetime."""
    return _now


def now_iso():
    """Current logical instant as a canonical ISO string."""
    return format_dt(_now)


def set_now(dt):
    global _now
    _now = dt
    return _now


def reset():
    return set_now(parse_dt(SEED))
