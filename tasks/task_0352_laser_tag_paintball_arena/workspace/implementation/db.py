"""In-memory data store. Starts empty on every boot — no seeding."""

import itertools
import threading
import uuid

from timeutil import now_iso

# A global lock makes every mutating request atomic, which matches the PRD's
# immediate-consistency model and the serial test harness.
LOCK = threading.RLock()

# One dict per entity collection, keyed by id. Insertion order is preserved by
# dict, giving us deterministic created_at-ascending iteration.
arenas = {}
fields = {}
party_packages = {}
bookings = {}
waiver_profiles = {}
equipment_units = {}
rentals = {}
add_on_orders = {}
referees = {}
referee_assignments = {}
leagues = {}
league_matches = {}

# Monotonic sequence stamped onto every record so created_at ties (same-ms
# creation) still sort deterministically by true creation order.
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def base_record():
    """System fields common to every entity: id, created_at, updated_at, version."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),
    }


def touch(record):
    """Mutation discipline (PRD §2.4): refresh updated_at and bump version."""
    record["updated_at"] = now_iso()
    record["version"] += 1
