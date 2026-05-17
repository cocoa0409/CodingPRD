"""In-memory data store + ID/timestamp/version helpers.

Per PRD §2.4, most entities carry id/created_at/updated_at/version. The
BillingLedgerEntry is the single exception — it has only id and created_at,
because ledger rows are immutable.

Per PRD §2.5, every Clinic has its own logical clock (`now_ts`). All timestamps
for entities owned by that clinic — created_at, updated_at, activated_at,
completed_at, actual_start, actual_end — are stamped from the OWNING clinic's
now_ts, never the wall clock. This keeps the test harness fully deterministic.
"""
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
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def stamp_create(record: dict, *, now: str, with_version: bool = True) -> dict:
    """Populate id, created_at, updated_at, version on creation."""
    if "id" not in record or record["id"] is None:
        record["id"] = new_id()
    record["created_at"] = now
    if with_version:
        record["updated_at"] = now
        record["version"] = 1
    return record


def stamp_update(record: dict, *, now: str) -> dict:
    """Refresh updated_at and bump version on mutation."""
    record["updated_at"] = now
    record["version"] = record.get("version", 0) + 1
    return record


class Store:
    """Container holding all entity tables."""

    def __init__(self):
        self.clinics: Dict[str, dict] = {}
        self.patients: Dict[str, dict] = {}
        self.therapists: Dict[str, dict] = {}
        self.evaluations: Dict[str, dict] = {}
        self.treatment_plans: Dict[str, dict] = {}
        self.authorizations: Dict[str, dict] = {}
        self.sessions: Dict[str, dict] = {}
        self.claims: Dict[str, dict] = {}
        self.ledger_entries: Dict[str, dict] = {}


_STORE: Optional[Store] = None


def reset_store() -> None:
    global _STORE
    _STORE = Store()


def get_store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = Store()
    return _STORE
