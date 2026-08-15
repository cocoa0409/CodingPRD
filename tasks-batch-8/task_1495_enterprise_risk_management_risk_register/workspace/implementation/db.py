"""In-memory store. Everything lives in module-level dicts keyed by id.

The store starts completely empty on every boot: no seeding, no preloading,
no on-disk persistence. Tests construct all state through the API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

store = {
    "categories": {},
    "risks": {},
    "assessments": {},
    "controls": {},
    "mappings": {},
    "appetite_statements": {},
    "breaches": {},
    "plans": {},
    "actions": {},
    "kris": {},
    "observations": {},
    "reports": {},
    "emerging_risks": {},
}

_seq_counter = itertools.count(1)

# PRD section 2.4: the logical clock starts at exactly 2026-08-01T00:00:00Z
# and never falls back to wall-clock time.
_logical_clock = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def wall_now():
    return datetime.now(timezone.utc)


def clock_now():
    return _logical_clock["now"]


def set_clock(dt):
    _logical_clock["now"] = dt
