"""In-memory data store and entity records.

Stores datetimes as Python datetime objects; serializers project them to
ISO 8601 UTC strings on the way out.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class _DataStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        # Start the clock at a stable epoch; tests advance it explicitly.
        self.clock: datetime = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

        # Primary indexes id -> entity dict
        self.elections: Dict[str, Dict[str, Any]] = {}
        self.precincts: Dict[str, Dict[str, Any]] = {}
        self.voters: Dict[str, Dict[str, Any]] = {}
        self.party_registrations: Dict[str, Dict[str, Any]] = {}
        self.absentee_ballots: Dict[str, Dict[str, Any]] = {}
        self.curing_cases: Dict[str, Dict[str, Any]] = {}
        self.ballot_casts: Dict[str, Dict[str, Any]] = {}
        self.voting_machines: Dict[str, Dict[str, Any]] = {}
        self.recount_requests: Dict[str, Dict[str, Any]] = {}

        # Insertion-order tracking for created_at-asc list ordering.
        self.insertion_order: Dict[str, List[str]] = {
            "elections": [],
            "precincts": [],
            "voters": [],
            "party_registrations": [],
            "absentee_ballots": [],
            "curing_cases": [],
            "ballot_casts": [],
            "voting_machines": [],
            "recount_requests": [],
        }

    def now(self) -> datetime:
        return self.clock

    def set_now(self, dt: datetime) -> None:
        self.clock = dt

    def insert(self, collection: str, entity: Dict[str, Any]) -> None:
        coll = getattr(self, collection)
        coll[entity["id"]] = entity
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
