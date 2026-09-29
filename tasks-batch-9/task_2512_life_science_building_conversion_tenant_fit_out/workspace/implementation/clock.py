"""The logical clock (PRD 2.4).

Time in this system is a logical clock, not the wall clock. It starts at
2026-08-01T00:00:00Z and any of the five roles may move it. Every temporal rule
-- proposal expiry, delivery windows, the vibration buffer, amenity windows,
expiration notices and the completed_at / permit_applied_at / permit_issued_at /
accepted_at / executed_at stamps -- is evaluated against this instant.
"""
from constants import LOGICAL_CLOCK_DEFAULT
from util import parse_iso

_current = parse_iso(LOGICAL_CLOCK_DEFAULT)


def now():
    return _current


def set_now(moment):
    global _current
    _current = moment
    return _current


def reset():
    global _current
    _current = parse_iso(LOGICAL_CLOCK_DEFAULT)
    return _current
