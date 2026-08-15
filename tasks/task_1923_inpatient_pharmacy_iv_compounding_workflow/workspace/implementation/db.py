"""In-memory data store.

All state lives in module-level dictionaries keyed by id. The store starts
completely empty on every boot; nothing is seeded. A single server-held
logical clock drives every timestamp the system produces (PRD Section 2.6):
before any client sets it, the clock reads exactly 2026-08-01T00:00:00Z.
"""

import uuid
from datetime import datetime, timezone


# --- entity tables (id -> dict) ---
staff = {}
patients = {}
drugs = {}
hoods = {}
sessions = {}
shifts = {}
orders = {}
interventions = {}
batches = {}
preparations = {}
stations = {}
pockets = {}
events = {}
discrepancies = {}
diversions = {}
protocols = {}
waste_records = {}

# --- logical clock ---
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = DEFAULT_CLOCK

# Monotonic insertion sequence; stable tie-break for equal timestamps.
_seq = 0


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    # Canonical hyphenated UUID string (PRD §2.4: "a server-minted UUID").
    return str(uuid.uuid4())


def base_fields():
    """Common fields for a versioned resource (PRD Section 2.4)."""
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def append_fields():
    """Common fields for an append-only record (no updated_at / version)."""
    return {
        "id": new_id(),
        "created_at": now(),
        "_seq": next_seq(),
    }


def touch(entity):
    """Record a mutation on a versioned resource: bump version, refresh ts."""
    entity["version"] += 1
    entity["updated_at"] = now()
