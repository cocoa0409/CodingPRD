"""In-memory data store.

A single ``Store`` instance owns per-entity dicts plus a global RLock that
serialises mutating operations.  Each entity is a plain ``dict``.

Per PRD §2.4, ``Invoice`` and ``FactoringAdvance`` are deliberately exempt
from the ``updated_at``/``version`` lifecycle fields — they carry only ``id``
and ``created_at`` because they exist as immutable financial records.  All
other entities receive the full lifecycle treatment.
"""

from __future__ import annotations

import threading
import uuid
from typing import Dict

from .timeutil import iso_now


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()

        self.brokerages: Dict[str, dict] = {}
        self.shippers: Dict[str, dict] = {}
        self.carriers: Dict[str, dict] = {}
        self.quote_requests: Dict[str, dict] = {}
        self.rate_contracts: Dict[str, dict] = {}
        self.loads: Dict[str, dict] = {}
        self.accessorial_charges: Dict[str, dict] = {}
        self.invoices: Dict[str, dict] = {}
        self.factoring_advances: Dict[str, dict] = {}
        self.dispute_claims: Dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------
    @staticmethod
    def stamp_create(entity: dict, *, versioned: bool = True, now: str | None = None) -> dict:
        now = now or iso_now()
        entity["id"] = entity.get("id") or new_id()
        entity["created_at"] = now
        if versioned:
            entity["updated_at"] = now
            entity["version"] = 1
        return entity

    @staticmethod
    def bump(entity: dict) -> None:
        """Refresh updated_at + increment version on a versioned entity.

        No-op on entities without a ``version`` field (Invoice, FactoringAdvance)
        — those are immutable per PRD §2.4 and only their computed money fields
        are updated in place by cascades, but they do not bear a version.
        """
        if "version" not in entity:
            return
        entity["updated_at"] = iso_now()
        entity["version"] = int(entity["version"]) + 1


store = Store()
