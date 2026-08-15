"""In-memory data store and logical clock.

All state lives in module-level dicts. Nothing is seeded at startup: the store
is completely empty on every boot and the logical clock starts at exactly
2026-08-01T00:00:00Z per the PRD.
"""
import itertools
from datetime import datetime, timezone

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self):
        self._current = CLOCK_START

    def now(self):
        return self._current

    def set(self, dt):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._current = dt.astimezone(timezone.utc)

    def current_date(self):
        return self._current.date()

    def current_date_str(self):
        return self._current.date().isoformat()


clock = LogicalClock()

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


# Entity stores, keyed by id. All start empty.
charters = {}
segments = {}
amendments = {}
applications = {}
members = {}
accounts = {}
transactions = {}
enrollments = {}
declarations = {}
payments = {}
meetings = {}
ballots = {}
reviews = {}
