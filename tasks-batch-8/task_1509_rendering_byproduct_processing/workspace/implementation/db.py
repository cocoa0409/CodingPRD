"""In-memory data store. Everything lives in process memory; a server restart
wipes all state (per-test-server isolation relies on this)."""
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

STORES = {
    "plants": {},
    "permits": {},
    "suppliers": {},
    "agreements": {},
    "vehicles": {},
    "wash_tickets": {},
    "routes": {},
    "stops": {},
    "batches": {},
    "cook_runs": {},
    "lots": {},
    "contracts": {},
    "orders": {},
    "index_entries": {},
    "odor_events": {},
    "settlements": {},
}

CLOCK = {"now": DEFAULT_NOW}
SEQ = {"n": 0}


def now():
    return CLOCK["now"]


def set_now(dt):
    CLOCK["now"] = dt


def next_seq():
    SEQ["n"] += 1
    return SEQ["n"]
