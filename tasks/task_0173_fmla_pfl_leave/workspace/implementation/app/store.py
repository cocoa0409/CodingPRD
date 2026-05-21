"""In-memory data store for all entities.

A single Store singleton holds dictionaries of entities keyed by `id`.
All access is serialized through a single re-entrant lock to guarantee
the concurrency semantics described in §1.2.1."""
from __future__ import annotations

import threading
import uuid
from typing import Dict


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.employers: Dict[str, dict] = {}
        self.worksites: Dict[str, dict] = {}
        self.employees: Dict[str, dict] = {}
        self.leave_cases: Dict[str, dict] = {}
        self.leave_instances: Dict[str, dict] = {}
        self.medical_certifications: Dict[str, dict] = {}
        self.pfl_claims: Dict[str, dict] = {}
        self.benefit_invoices: Dict[str, dict] = {}
        self.audit_events: Dict[str, dict] = {}

        # Insertion counters for deterministic ordering on equal timestamps
        self._counter = 0

    def next_seq(self) -> int:
        with self.lock:
            self._counter += 1
            return self._counter


_STORE = Store()


def get_store() -> Store:
    return _STORE


def reset_store() -> None:
    """Wipe everything — exposed for tests but not bound to an endpoint."""
    s = _STORE
    with s.lock:
        s.employers.clear()
        s.worksites.clear()
        s.employees.clear()
        s.leave_cases.clear()
        s.leave_instances.clear()
        s.medical_certifications.clear()
        s.pfl_claims.clear()
        s.benefit_invoices.clear()
        s.audit_events.clear()
        s._counter = 0
