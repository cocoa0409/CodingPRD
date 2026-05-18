"""In-memory data store and entity records.

Every entity is a plain dict so that serializers stay simple. The store also tracks
the logical clock and provides a single lock for thread-safe mutation.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class _DataStore:
    """Holds every collection plus the logical clock."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.clock: datetime = datetime.now(tz=timezone.utc)

        # Primary indexes — id -> entity dict
        self.units: Dict[str, Dict[str, Any]] = {}
        self.members: Dict[str, Dict[str, Any]] = {}
        self.assessment_cycles: Dict[str, Dict[str, Any]] = {}
        self.assessment_charges: Dict[str, Dict[str, Any]] = {}
        self.payments: Dict[str, Dict[str, Any]] = {}
        self.acc_requests: Dict[str, Dict[str, Any]] = {}
        self.acc_votes: Dict[str, Dict[str, Any]] = {}
        self.violations: Dict[str, Dict[str, Any]] = {}
        self.board_resolutions: Dict[str, Dict[str, Any]] = {}
        self.board_votes: Dict[str, Dict[str, Any]] = {}  # vote bookkeeping
        self.elections: Dict[str, Dict[str, Any]] = {}
        self.candidates: Dict[str, Dict[str, Any]] = {}
        self.ballots: Dict[str, Dict[str, Any]] = {}
        self.liens: Dict[str, Dict[str, Any]] = {}
        self.reserve_studies: Dict[str, Dict[str, Any]] = {}

        # Insertion-order tracking for created_at-asc list ordering.
        self.insertion_order: Dict[str, List[str]] = {
            "units": [],
            "members": [],
            "assessment_cycles": [],
            "assessment_charges": [],
            "payments": [],
            "acc_requests": [],
            "acc_votes": [],
            "violations": [],
            "board_resolutions": [],
            "board_votes": [],
            "elections": [],
            "candidates": [],
            "ballots": [],
            "liens": [],
            "reserve_studies": [],
        }

    def now(self) -> datetime:
        return self.clock

    def set_now(self, dt: datetime) -> None:
        self.clock = dt

    def insert(self, collection: str, entity: Dict[str, Any]) -> None:
        store = getattr(self, collection)
        store[entity["id"]] = entity
        self.insertion_order[collection].append(entity["id"])


_STORE: Optional[_DataStore] = None


def reset_store() -> None:
    global _STORE
    _STORE = _DataStore()


def store() -> _DataStore:
    global _STORE
    if _STORE is None:
        _STORE = _DataStore()
    return _STORE
