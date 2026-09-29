"""In-memory store and the logical clock (PRD sections 2.4, 2.5).

The store is created empty on every process boot.  Nothing is ever seeded,
preloaded or hardcoded here, and nothing is persisted to disk.
"""

import threading
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "hospital_contracts",
    "surgeons",
    "preference_cards",
    "perfusionists",
    "certifications",
    "ce_activities",
    "perfusion_devices",
    "device_event_logs",
    "call_rotation_slots",
    "bypass_cases",
    "disposable_packs",
    "pump_checklists",
    "ecmo_runs",
    "incident_reports",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_new(row):
    """Attach the common fields (PRD 2.4): id, created_at, updated_at, version."""
    row["id"] = new_id()
    row["created_at"] = db.now()
    row["updated_at"] = db.now()
    row["version"] = 1
    row["_seq"] = db.next_seq()
    return row


def stamp_log(row):
    """DeviceEventLog carries only id and created_at (PRD 2.4)."""
    row["id"] = new_id()
    row["created_at"] = db.now()
    row["_seq"] = db.next_seq()
    return row


def touch(row):
    """Refresh updated_at and advance version by exactly 1 (PRD 2.4 / 2.9)."""
    row["updated_at"] = db.now()
    row["version"] = row.get("version", 0) + 1
    return row


def insert(collection, row):
    getattr(db, collection)[row["id"]] = row
    return row


def ordered(collection):
    """Every collection listing is ordered by created_at ascending (PRD 2.3);
    insertion sequence breaks ties deterministically."""
    rows = list(getattr(db, collection).values())
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
