"""In-memory data store (PRD 2.4).

A fresh process starts with empty collections — no seeding, no preload. Every
entity is keyed by its server-minted UUID. All collections are plain dicts.
"""

import uuid
from datetime import datetime, timezone

# One dict per entity type, keyed by id.
COLLECTIONS = [
    "dealerships",
    "customers",
    "units",
    "deals",
    "pdi_inspections",
    "service_bays",
    "service_orders",
    "part_items",
    "part_reservations",
    "warranty_plans",
    "appointments",
    "storage_slots",
    "recall_campaigns",
    "recall_remedies",
]

store = {name: {} for name in COLLECTIONS}


def reset():
    for name in COLLECTIONS:
        store[name] = {}


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Server wall-clock timestamp, ISO 8601 UTC with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
