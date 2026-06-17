"""In-memory data store.

The store starts EMPTY on every boot. Nothing is seeded. Tests build all
state through the declared API surface.

Common fields (PRD §2.4): every entity carries
  id          UUID, no type prefix
  created_at  ISO 8601 UTC, three fractional digits
  updated_at  ISO 8601 UTC, three fractional digits (refreshed on every change)
  version     integer, starts at 1, +1 on every mutation
"""

import threading
import uuid
from datetime import datetime, timezone


# A single global lock makes every request observe a serial history, which is
# what the OCC/conservation invariants require.
LOCK = threading.RLock()


def _now():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.bureaus = {}
        self.customers = {}
        self.materials = {}
        self.machines = {}
        self.spools = {}
        self.print_files = {}
        self.orders = {}
        self.order_lines = {}
        self.finishing_tasks = {}
        self.print_runs = {}
        self.shipments = {}


DB = Store()


def reset():
    """Reset to an empty store (used only for completeness; not called at boot)."""
    global DB
    DB = Store()


def stamp_create(entity):
    """Populate the system common fields on a freshly created entity."""
    ts = _now()
    entity.setdefault("id", new_id())
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    """Apply a mutation stamp: bump version and refresh updated_at."""
    entity["updated_at"] = _now()
    entity["version"] = entity.get("version", 0) + 1
    return entity
