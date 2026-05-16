"""In-memory data store.

Each collection is keyed by id. All mutating writes go through helpers in this
module so id/created_at/updated_at/version semantics are uniform.

NOTE: The clock module's now() is used for created_at / updated_at so test-driven
clock advances apply uniformly.
"""

import threading
import uuid
from typing import Dict

from clock import now
from response import iso_utc_ms


# Master locking primitive for serializing critical sections (capacity updates,
# CLEP award uniqueness, etc.).
db_lock = threading.RLock()


class Store:
    """A collection backed by a dict keyed by id."""

    def __init__(self):
        self._data: Dict[str, dict] = {}

    def insert(self, obj: dict) -> dict:
        self._data[obj["id"]] = obj
        return obj

    def get(self, _id: str):
        return self._data.get(_id)

    def all(self):
        return list(self._data.values())

    def remove(self, _id: str):
        self._data.pop(_id, None)


# Storage collections
test_events = Store()
test_centers = Store()
test_center_capacities = Store()  # keyed by capacity row id
candidates = Store()
registrations = Store()
accommodation_requests = Store()
id_verifications = Store()  # one per registration
score_reports = Store()
clep_credit_awards = Store()
refund_transactions = Store()


# Helpers to track per-event deadline extension usage (only one extension allowed).
deadline_extensions_used: Dict[str, bool] = {}

# Track whether a no-show sweep has been called for a given test event at least once
# after test_date (precondition for REGISTRATION_CLOSED → SCORES_PENDING).
sweep_called_after_test_date: Dict[str, bool] = {}


def new_id() -> str:
    """Return a UUID string with no prefix."""
    return str(uuid.uuid4())


def common_create() -> dict:
    """Return a dict of common fields for a new resource."""
    n = now()
    return {
        "id": new_id(),
        "created_at": iso_utc_ms(n),
        "updated_at": iso_utc_ms(n),
        "version": 1,
    }


def append_create() -> dict:
    """Return common fields for an append-only resource (id, created_at only)."""
    n = now()
    return {
        "id": new_id(),
        "created_at": iso_utc_ms(n),
    }


def touch(obj: dict) -> dict:
    """Bump version + updated_at on a mutating write."""
    if "version" in obj:
        obj["version"] = int(obj.get("version", 1)) + 1
    obj["updated_at"] = iso_utc_ms(now())
    return obj
