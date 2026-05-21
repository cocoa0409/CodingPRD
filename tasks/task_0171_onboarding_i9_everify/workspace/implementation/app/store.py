"""In-memory data store for all entities.

This module provides a single Store singleton holding dictionaries
of entities keyed by id. All access is serialized through a single
re-entrant lock to guarantee the concurrency semantics described in
§2.10 (first-writer-wins for contended resources)."""
from __future__ import annotations

import threading
import uuid
from typing import Any, Dict, Optional


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.employees: Dict[str, dict] = {}
        self.i9_documents: Dict[str, dict] = {}
        self.i9_forms: Dict[str, dict] = {}
        self.everify_cases: Dict[str, dict] = {}
        self.reverification_events: Dict[str, dict] = {}
        self.audit_events: Dict[str, dict] = {}

        # Indices for concurrency control / fast lookups
        # (employee_id, idempotency_key) -> case_id
        self.idempotency_index: Dict[tuple, str] = {}
        # employee_id -> bool — has an INITIAL form already been created?
        self.initial_form_index: Dict[str, str] = {}
        # ssn -> employee_id — uniqueness across non-terminated employees
        self.ssn_index: Dict[str, str] = {}

        # Insertion-order counters to break created_at ties deterministically
        self._counter = 0

    def next_seq(self) -> int:
        with self.lock:
            self._counter += 1
            return self._counter


_STORE = Store()


def get_store() -> Store:
    return _STORE
