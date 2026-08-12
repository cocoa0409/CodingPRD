"""In-memory data store. Fresh on every process boot — no seeding, no disk I/O.

The store starts empty on every boot; every entity any test needs is built via
the declared API surface. The logical clock (PRD §2.5) starts at exactly
2026-05-01T00:00:00Z and only moves through POST /_clock/set_current_utc.
"""
from datetime import datetime, timezone

# Entity stores, keyed by id.
STORE = {
    "members": {},
    "site_agreements": {},
    "repeaters": {},
    "coordination_requests": {},
    "net_sessions": {},
    "check_ins": {},
    "agency_agreements": {},
    "activations": {},
    "roster_entries": {},
    "drills": {},
    "drill_messages": {},
    "field_day_events": {},
    "field_day_contacts": {},
    "exam_sessions": {},
    "exam_candidates": {},
    "equipment_loans": {},
}

# Monotonic insertion sequence (deterministic tie-break for created_at sort).
_SEQ = {"n": 0}

# Logical clock (PRD §2.5): startup default is exactly 2026-05-01T00:00:00Z.
CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def now():
    return CLOCK["now"]


def set_now(dt):
    CLOCK["now"] = dt
