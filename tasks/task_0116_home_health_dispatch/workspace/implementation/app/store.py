"""In-memory data store with UUID + timestamp + version helpers."""
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional


_LOCK = threading.RLock()


def get_lock() -> threading.RLock:
    return _LOCK


def new_id() -> str:
    return str(uuid.uuid4())


def real_now_iso() -> str:
    """Wall-clock ISO 8601 UTC with millisecond precision."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def stamp_create(record: dict, *, with_version: bool = True, now: Optional[str] = None) -> dict:
    """Populate id, created_at, updated_at, version on creation."""
    if "id" not in record or record["id"] is None:
        record["id"] = new_id()
    ts = now if now is not None else real_now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    if with_version:
        record["version"] = 1
    return record


def stamp_update(record: dict, *, with_version: bool = True, now: Optional[str] = None) -> dict:
    """Refresh updated_at and bump version on mutation."""
    ts = now if now is not None else real_now_iso()
    record["updated_at"] = ts
    if with_version:
        record["version"] = record.get("version", 0) + 1
    return record


class Store:
    """Container holding all entity tables and the logical date clock."""

    def __init__(self):
        self.patients: Dict[str, dict] = {}
        self.clinicians: Dict[str, dict] = {}
        self.oasis_assessments: Dict[str, dict] = {}
        self.episodes: Dict[str, dict] = {}
        self.visits: Dict[str, dict] = {}
        self.mileage_logs: Dict[str, dict] = {}
        self.pdgm_claims: Dict[str, dict] = {}
        # ClockState — a logical date (YYYY-MM-DD) driven by tests, default 1970-01-01.
        # Stored as a dict so it remains a simple mutable singleton.
        self.clock: dict = {"current_date": "1970-01-01"}


_STORE: Optional[Store] = None


def reset_store() -> None:
    global _STORE
    _STORE = Store()


def get_store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = Store()
    return _STORE
