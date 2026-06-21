import uuid
import threading
from response import iso_now


class DB:
    """In-memory store. Starts empty on every boot; no seeding."""

    def __init__(self):
        self.zones = {}
        self.drivers = {}
        self.riders = {}
        self.snapshots = {}
        self.trips = {}
        self.queue_entries = {}
        self.quests = {}
        self.disputes = {}
        self.lock = threading.RLock()
        # monotonically-increasing sequence to provide a stable secondary sort
        # for resources created within the same millisecond timestamp.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_id():
    return str(uuid.uuid4())


def common_fields():
    """id, created_at, updated_at, version for standard resources."""
    now = iso_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Refresh updated_at and bump version on mutation."""
    entity["updated_at"] = iso_now()
    entity["version"] = entity.get("version", 1) + 1


def public(entity):
    """Strip internal fields (those starting with _) for serialization."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
