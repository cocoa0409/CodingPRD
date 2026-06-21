"""Logical clock (PRD §2.7).

The system runs against a logical clock rather than wall-clock time. A platform
administrator may set the current clock instant via POST /_clock/set.

Until the clock is set, the current instant defaults to the process boot time
(real UTC now). This is per-process state and is wiped on every restart.
"""
from datetime import datetime, timezone

_now = datetime.now(timezone.utc)


def get_now():
    return _now


def set_now(dt):
    global _now
    _now = dt
