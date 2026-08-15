"""In-memory data store and logical clock.

The store starts empty on every boot — no seeding. All entities are created
through the declared API surface. The logical clock starts at exactly
2026-08-01T00:00:00Z and is only moved by POST /_clock/set_current_utc.
"""

import itertools
from datetime import datetime, timezone

# --- Logical clock -----------------------------------------------------------
_CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock_now = _CLOCK_START


def now():
    return _clock_now


def set_clock(dt):
    global _clock_now
    _clock_now = dt


# --- Entity stores (keyed by id) ----------------------------------------------
carriers = {}
escorts = {}
jobs = {}
legs = {}
permits = {}
surveys = {}
obstructions = {}
assignments = {}
delay_events = {}
incidents = {}
invoices = {}

# Monotonic creation sequence for stable created_at tie-breaking.
_seq = itertools.count(1)


def next_seq():
    return next(_seq)
