"""In-memory data store, UUID generation, and a global write lock."""

import uuid
from threading import RLock


def new_id() -> str:
    return str(uuid.uuid4())


# Single global lock to serialize state-changing operations. This gives us the
# first-writer-wins guarantees that the PRD §2.9 requires without resorting to
# per-aggregate locks.
LOCK = RLock()


DB = {
    "rooms": {},
    "housekeepers": {},
    "cleaning_tasks": {},
    "minibar_items": {},
    "minibar_consumptions": {},
    "maintenance_tickets": {},
    "linen_types": {},
    "linen_movements": {},
    "inspection_records": {},
    "room_status_events": {},  # id -> event
    "audit_logs": {},
}


def reset():
    for k in DB:
        DB[k] = {}
