"""In-memory data store.

A single ``Store`` instance owns the per-entity dicts and the global lock
used to serialise mutating operations.  Each entity is represented by a
plain dict with the field names defined in SCAFFOLD §1.1.
"""

from __future__ import annotations

import threading
import uuid
from typing import Dict, Optional

from .timeutil import iso_now


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()

        self.requesters: Dict[str, dict] = {}
        self.requests: Dict[str, dict] = {}
        self.responsive_records: Dict[str, dict] = {}
        self.exemption_claims: Dict[str, dict] = {}
        self.third_party_notices: Dict[str, dict] = {}
        self.appeals: Dict[str, dict] = {}
        self.fee_assessments: Dict[str, dict] = {}
        self.audit_entries: Dict[str, dict] = {}

    # ----- common helpers -----
    @staticmethod
    def stamp_create(entity: dict, *, versioned: bool = True) -> dict:
        now = iso_now()
        entity["id"] = entity.get("id") or new_id()
        entity["created_at"] = now
        if versioned:
            entity["updated_at"] = now
            entity["version"] = 1
        return entity

    @staticmethod
    def bump(entity: dict) -> None:
        """Refresh updated_at and increment version on a versioned entity."""
        entity["updated_at"] = iso_now()
        entity["version"] = int(entity.get("version", 1)) + 1


store = Store()


# ----- Audit -----
def append_audit(
    *,
    subject_type: str,
    subject_id: str,
    event_code: str,
    actor_role: Optional[str],
    actor_id: Optional[str],
    payload: Optional[dict] = None,
) -> dict:
    entry = {
        "id": new_id(),
        "created_at": iso_now(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "event_code": event_code,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "payload": payload or {},
    }
    store.audit_entries[entry["id"]] = entry
    return entry
