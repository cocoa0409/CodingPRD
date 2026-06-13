"""In-memory data store. Starts empty on every boot — NO seeding.

All state lives in module-level dicts keyed by UUID id. Re-importing this module
(fresh process via start.sh) gives a pristine, empty store.
"""
import uuid
from datetime import datetime, timezone


def _now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


# One dict per entity type, keyed by id.
gates = {}
remote_stands = {}
cute_units = {}
ground_equipment = {}
flights = {}
slot_permits = {}
gate_assignments = {}
cute_allocations = {}
gse_allocations = {}

# Singleton simulated clock (ClockState). current_utc is None until set.
clock = {"current_utc": None}

# Monotonic creation sequence to provide a stable secondary sort key when two
# records share the same millisecond created_at timestamp.
_seq_counter = {"n": 0}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def stamp_create(record):
    """Attach the common system fields on create (PRD §2.4)."""
    ts = _now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Refresh updated_at and bump version on every mutation (PRD §2.4)."""
    record["updated_at"] = _now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
