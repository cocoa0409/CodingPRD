"""In-memory data store (PRD §2.4 common resource properties).

Every persisted resource carries id (UUID, no type prefix), created_at,
updated_at, and version. The store starts empty on every boot — no seeding.
"""
import uuid
from datetime import datetime, timezone

# One dict per entity collection, keyed by id. Insertion order is preserved by
# dict (Python 3.7+), which gives the created_at-ascending default sort.
stores = {}
products = {}
inventory_lots = {}
livestock_batches = {}
customers = {}
prescriptions = {}
clinic_appointments = {}
subscriptions = {}
shipments = {}
special_orders = {}
recalls = {}
adoption_events = {}
adoption_placements = {}


def new_id():
    """UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def stamp_create(record):
    """Set system-managed creation fields: id, created_at, updated_at, version."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """A mutation: increment version and refresh updated_at together (PRD §2.4)."""
    record["version"] += 1
    record["updated_at"] = now_iso()
