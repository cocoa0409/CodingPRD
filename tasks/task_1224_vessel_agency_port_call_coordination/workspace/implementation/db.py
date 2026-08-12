"""In-memory data store and logical clock.

Storage is in-memory only: plain dicts keyed by id. Nothing is seeded at
startup; every entity is created through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

STORES = {
    "principals": {},
    "port_calls": {},
    "authority_notifications": {},
    "berth_windows": {},
    "service_orders": {},
    "crew_changes": {},
    "vendors": {},
    "purchase_orders": {},
    "cargo_documents": {},
    "tariffs": {},
    "disbursement_accounts": {},
    "da_lines": {},
    "funding_advances": {},
    "cost_disputes": {},
    "husbandry_cases": {},
}

# Monotonic insertion sequence used as a stable tie-breaker when several
# resources share the same created_at (the logical clock may not move
# between creates).
_seq = itertools.count(1)

# Logical clock. Startup default is exactly 2026-05-01T00:00:00Z; the server
# never falls back to wall-clock time.
CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return CLOCK["now"]


def set_now(dt):
    CLOCK["now"] = dt


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())
