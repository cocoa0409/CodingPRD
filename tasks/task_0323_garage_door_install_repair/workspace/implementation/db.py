"""In-memory data store. Starts EMPTY on every boot — no seeding.

Each collection is a dict keyed by the resource's UUID id. Entities are plain
dicts. Common system fields (created_at / updated_at / version) are managed
here per PRD §2.4.
"""
import uuid
from datetime import datetime, timezone

# Collections keyed by id
customers = {}
technicians = {}
door_models = {}
opener_models = {}
parts = {}
equipment_units = {}
quotes = {}
quote_lines = {}
jobs = {}
part_reservations = {}
warranty_plans = {}
financing_applications = {}
callbacks = {}

# monotonic insertion counter used as a tiebreaker for created_at ascending sort
_seq = [0]


def reset():
    """Wipe every byte of state. Called at process start (defensive)."""
    for c in (customers, technicians, door_models, opener_models, parts,
              equipment_units, quotes, quote_lines, jobs, part_reservations,
              warranty_plans, financing_applications, callbacks):
        c.clear()
    _seq[0] = 0


def new_id():
    return str(uuid.uuid4())


def _now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def next_seq():
    _seq[0] += 1
    return _seq[0]


def stamp_create(entity, common_fields=True, versioned=True):
    """Attach id, created_at, and (when applicable) updated_at/version."""
    entity["id"] = new_id()
    entity["created_at"] = _now_iso()
    entity["_seq"] = next_seq()
    if common_fields:
        if versioned:
            entity["updated_at"] = entity["created_at"]
            entity["version"] = 1
    return entity


def touch(entity):
    """Bump updated_at and version on mutation (PRD §2.4)."""
    if "version" in entity:
        entity["version"] += 1
        entity["updated_at"] = _now_iso()
