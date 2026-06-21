"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts EMPTY on every process boot. Nothing is seeded or preloaded;
every entity is created by the test suite through the declared API surface.
"""
import itertools
import uuid

from response import now_iso

# -- collections (full-lifecycle entities carry id/created_at/updated_at/version) --
corporate_accounts = {}
affiliates = {}
vehicle_classes = {}
vehicles = {}
chauffeurs = {}
reservations = {}
flight_trackings = {}
assignments = {}
farm_out_orders = {}

# -- lean records: id + created_at only --
wait_events = {}
cancellation_records = {}

# -- singleton-like server clock --
clock = {"current_utc": None}

# monotonic sequence so created_at ties have a deterministic insertion order
_seq = itertools.count()


def new_id():
    # UUID with no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def new_full(fields):
    """Create a full-lifecycle record: id, created_at, updated_at, version=1."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(fields)
    return rec


def new_lean(fields):
    """Create a lean record: id + created_at only (PRD §2.4)."""
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    rec.update(fields)
    return rec


def touch(rec):
    """Refresh updated_at and bump version on any mutation (PRD §2.4)."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 0) + 1
