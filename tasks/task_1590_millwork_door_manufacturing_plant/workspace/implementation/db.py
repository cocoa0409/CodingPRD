"""In-memory data store.

The store starts completely empty on every boot. No entity is seeded,
preloaded, or hardcoded; all records are created exclusively through the
declared API surface at request time.
"""

import uuid
from datetime import datetime, timezone

# One dict per resource collection, keyed by resource id.
projects = {}
hardware_templates = {}
moulder_machines = {}
spray_booths = {}
fire_label_rolls = {}
orders = {}
openings = {}
shop_drawings = {}
machining_programs = {}
moulder_setup_slots = {}
finishing_batches = {}
label_allocations = {}
delivery_trips = {}
punch_items = {}


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits (e.g. 2026-08-13T10:30:00.123Z)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_record():
    """Fresh common-fields skeleton for a new resource."""
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(rec):
    """Refresh updated_at and bump version on a mutated resource."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1
