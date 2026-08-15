"""In-memory data store. Entirely process-local: a fresh boot starts empty.

NO seeding, preloading, or hardcoded entity data anywhere in this module or
its consumers — every entity is created through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timezone

LOCK = threading.RLock()

STORE = {
    "material_lots": {},
    "regrind_batches": {},
    "tools": {},
    "packaging_specs": {},
    "production_orders": {},
    "material_allocations": {},
    "machine_resources": {},
    "forming_runs": {},
    "scrap_records": {},
    "quality_inspections": {},
    "assembly_tasks": {},
    "cleanliness_certificates": {},
}

_SEQ = [0]


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def new_id():
    return str(uuid.uuid4())


def now_str():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---- Server logical clock (PRD §2.5) ----
DEFAULT_CLOCK_RAW = "2026-05-01T00:00:00Z"
CLOCK = {"dt": datetime(2026, 5, 1, tzinfo=timezone.utc), "raw": DEFAULT_CLOCK_RAW}


def logical_now():
    return CLOCK["dt"]


def set_logical_clock(dt, raw):
    CLOCK["dt"] = dt
    CLOCK["raw"] = raw


def new_record(common=True):
    """Fresh system-managed fields. common=False -> scrap record / certificate
    (id + created_at only, no updated_at/version per PRD §2.4)."""
    rec = {
        "id": new_id(),
        "created_at": now_str(),
        "_seq": next_seq(),
    }
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def bump(rec):
    """Refresh updated_at and advance version by exactly one (PRD §2.4)."""
    rec["updated_at"] = now_str()
    rec["version"] += 1
