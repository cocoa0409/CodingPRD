"""Server-side logical clock (PRD 2.6).

Starts at exactly 2026-08-01T00:00:00Z on every boot, never advances on its own,
and only ever moves forward through POST /_clock/set_current_utc.
"""
from constants import CLOCK_START_ISO
from util import parse_dt

_START = parse_dt(CLOCK_START_ISO)


class Clock:
    def __init__(self):
        self.current = _START

    def reset(self):
        self.current = _START


_clock = Clock()


def now():
    return _clock.current


def set_now(dt):
    _clock.current = dt


def reset():
    _clock.reset()
