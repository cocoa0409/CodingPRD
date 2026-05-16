"""In-memory data store. PRD §2.4 common fields are added at create-time."""

import uuid
import threading
from datetime import datetime, timezone

from core.clock import CLOCK


_LOCK = threading.RLock()


class Store:
    def __init__(self):
        # Top-level resources (id -> dict)
        self.districts = {}
        self.parent_accounts = {}
        self.students = {}
        self.frl_applications = {}
        self.menu_items = {}
        self.meal_serving_records = {}
        self.usda_claims = {}
        # Append-only event entities (id -> dict)
        self.allergy_entries = {}
        self.ledger_entries = {}
        # Monotonic sequence used for stable created_at tie-breaks
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def reset(self):
        self.districts.clear()
        self.parent_accounts.clear()
        self.students.clear()
        self.frl_applications.clear()
        self.menu_items.clear()
        self.meal_serving_records.clear()
        self.usda_claims.clear()
        self.allergy_entries.clear()
        self.ledger_entries.clear()
        self._seq = 0


STORE = Store()


def lock():
    return _LOCK


def gen_id() -> str:
    return str(uuid.uuid4())


def gen_request_id() -> str:
    """Per PRD §2.2: starts with req_ followed by alphanumeric."""
    return "req_" + uuid.uuid4().hex[:20]


def iso_from_dt(dt: datetime) -> str:
    """ISO 8601 UTC with 3 fractional digits and trailing Z (PRD §2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return iso_from_dt(CLOCK.now())


# --- Common-field helpers --------------------------------------------------

def stamp_common(obj: dict) -> dict:
    """Stamp id, created_at, updated_at, version on a new resource."""
    obj.setdefault("id", gen_id())
    n = now_iso()
    obj["created_at"] = n
    obj["updated_at"] = n
    obj["version"] = 1
    obj["_seq"] = STORE.next_seq()
    return obj


def stamp_append_only(obj: dict) -> dict:
    """Stamp id and created_at only (for AllergyProfileEntry, PaidLedgerEntry)."""
    obj.setdefault("id", gen_id())
    obj["created_at"] = now_iso()
    obj["_seq"] = STORE.next_seq()
    return obj


def touch(obj: dict):
    """Bump updated_at and version on a mutated resource."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
