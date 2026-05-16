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


def _now_iso_default() -> str:
    """Return the logical clock if available, falling back to wall clock.

    All audit timestamps (created_at, updated_at) are tied to the same logical
    clock as business-time fields (submitted_at, expires_at, ...) so that tests
    that advance /_clock/advance produce internally consistent records.
    """
    if _STORE is not None:
        return _STORE.clock["now"]
    return real_now_iso()


def stamp_create(record: dict, *, with_version: bool = True, now: Optional[str] = None) -> dict:
    """Populate id, created_at, updated_at, version on creation."""
    if "id" not in record or record["id"] is None:
        record["id"] = new_id()
    ts = now if now is not None else _now_iso_default()
    record["created_at"] = ts
    record["updated_at"] = ts
    if with_version:
        record["version"] = 1
    return record


def stamp_update(record: dict, *, with_version: bool = True, now: Optional[str] = None) -> dict:
    """Refresh updated_at and bump version on mutation."""
    ts = now if now is not None else _now_iso_default()
    record["updated_at"] = ts
    if with_version:
        record["version"] = record.get("version", 0) + 1
    return record


class Store:
    """Container holding all entity tables and the simulated test clock."""

    def __init__(self):
        self.patients: Dict[str, dict] = {}
        self.providers: Dict[str, dict] = {}
        self.catalog_items: Dict[str, dict] = {}
        self.authorization_requests: Dict[str, dict] = {}
        self.clinical_evidence: Dict[str, dict] = {}
        self.peer_to_peer_reviews: Dict[str, dict] = {}
        self.decisions: Dict[str, dict] = {}
        self.appeals: Dict[str, dict] = {}
        # Default logical clock: epoch. Tests advance it explicitly via /_clock/advance.
        self.clock: dict = {"now": "1970-01-01T00:00:00.000Z"}


_STORE: Optional[Store] = None


def reset_store() -> None:
    global _STORE
    _STORE = Store()


def get_store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = Store()
    return _STORE
