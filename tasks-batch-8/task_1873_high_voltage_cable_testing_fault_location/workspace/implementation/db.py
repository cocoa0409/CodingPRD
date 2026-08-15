"""In-memory data store and the server-side logical clock.

The store starts completely empty on every boot -- no seeding of any kind.
The logical clock starts at exactly 2026-08-01T00:00:00Z and never falls
back to wall-clock time; it advances only via the set_current_utc endpoint.
"""
import itertools
from datetime import datetime, timezone

circuits = {}
windows = {}
jobs = {}
permits = {}
series = {}
readings = {}
faults = {}
excavations = {}
splices = {}
units = {}
assignments = {}
assessments = {}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt
