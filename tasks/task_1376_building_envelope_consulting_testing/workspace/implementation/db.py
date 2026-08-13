"""In-memory data store and logical clock.

The store starts EMPTY on every boot. Nothing is seeded here or anywhere else;
every entity is created through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

STORE = {
    "engagements": {},
    "assemblies": {},
    "design_reviews": {},
    "chamber_slots": {},
    "mock_ups": {},
    "field_tests": {},
    "surveys": {},
    "anomalies": {},
    "remediation_plans": {},
    "warranty_claims": {},
    "litigation_holds": {},
    "maintenance_visits": {},
    "invoices": {},
    # Provisional-accrual event log: {"engagement_id", "ts", "seq", "delta", "kind"}
    "fee_events": [],
}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


# Logical clock: never falls back to wall-clock time. Startup default is
# exactly 2026-08-01T00:00:00Z per PRD section 2.4.
CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return CLOCK["now"]


def set_clock(dt):
    CLOCK["now"] = dt
