"""In-memory data store. Fresh on every process boot — no seeding, no disk I/O."""
from datetime import datetime, timezone

# Entity stores, keyed by id.
STORE = {
    "plans": {},
    "buildings": {},
    "students": {},
    "paras": {},
    "scos": {},
    "assignments": {},
    "coverage_plans": {},
    "absences": {},
    "backfills": {},
    "timesheets": {},
    "evaluations": {},
    "formulas": {},
    "allocations": {},
}

# Monotonic insertion sequence (deterministic tie-break; never exposed).
_SEQ = {"n": 0}

# Logical clock (PRD §2.4): startup default is exactly 2026-05-01T00:00:00Z.
CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def now():
    return CLOCK["now"]


def set_now(dt):
    CLOCK["now"] = dt
