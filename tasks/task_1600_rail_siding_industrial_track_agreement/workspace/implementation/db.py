"""In-memory data store. The store starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone

DB = {
    "agreements": {},
    "amendments": {},
    "construction_projects": {},
    "segments": {},
    "inspections": {},
    "derail_devices": {},
    "service_orders": {},
    "car_dwells": {},
    "storage_placements": {},
    "liability_claims": {},
}

# Logical clock: startup default 2026-08-01T00:00:00Z, never wall-clock.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
LOGICAL_CLOCK = {"current": DEFAULT_CLOCK}


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp used for created_at/updated_at (not the logical clock)."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
