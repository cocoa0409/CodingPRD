"""In-memory data store with UUID + timestamp + version helpers."""
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional


# Global mutation lock — coarse-grained but sufficient for these benchmark tests.
_LOCK = threading.RLock()


def get_lock() -> threading.RLock:
    return _LOCK


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def stamp_create(record: dict, *, with_version: bool = True) -> dict:
    """Populate id, created_at, updated_at, version on creation."""
    if "id" not in record or record["id"] is None:
        record["id"] = new_id()
    ts = now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    if with_version:
        record["version"] = 1
    return record


def stamp_update(record: dict, *, with_version: bool = True) -> dict:
    """Bump updated_at and version on mutation."""
    record["updated_at"] = now_iso()
    if with_version:
        record["version"] = record.get("version", 0) + 1
    return record


class Store:
    """Container holding all entity tables and the singleton clock."""

    def __init__(self):
        self.districts: Dict[str, dict] = {}
        self.schools: Dict[str, dict] = {}
        self.programs: Dict[str, dict] = {}
        self.families: Dict[str, dict] = {}
        self.students: Dict[str, dict] = {}
        self.applications: Dict[str, dict] = {}
        self.transfer_requests: Dict[str, dict] = {}
        self.lottery_runs: Dict[str, dict] = {}
        self.waitlist_events: Dict[str, dict] = {}
        # Singleton clock — `id == 'clock'`. Default is the epoch 1970-01-01T00:00:00Z,
        # which is conservative: every program registration window will be in the future.
        self.clock: dict = {
            "id": "clock",
            "now": "1970-01-01T00:00:00.000Z",
        }


_STORE: Optional[Store] = None


def reset_store() -> None:
    global _STORE
    _STORE = Store()


def get_store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = Store()
    return _STORE
