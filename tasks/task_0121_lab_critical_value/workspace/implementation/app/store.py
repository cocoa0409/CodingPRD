"""In-memory data store — row tables keyed by id, with a global RLock."""
from __future__ import annotations

from threading import RLock
from typing import Any


class _Tables:
    def __init__(self) -> None:
        self.patients: dict[str, dict[str, Any]] = {}
        self.clinicians: dict[str, dict[str, Any]] = {}
        self.test_panels: dict[str, dict[str, Any]] = {}
        self.lab_orders: dict[str, dict[str, Any]] = {}
        self.specimens: dict[str, dict[str, Any]] = {}
        self.transport_legs: dict[str, dict[str, Any]] = {}
        self.lab_results: dict[str, dict[str, Any]] = {}
        self.critical_notifications: dict[str, dict[str, Any]] = {}
        self.acknowledgement_receipts: dict[str, dict[str, Any]] = {}
        self.retest_requests: dict[str, dict[str, Any]] = {}
        self.audit_events: dict[str, dict[str, Any]] = {}

        # Lookup indexes
        self.specimen_by_lab_order: dict[str, str] = {}  # lab_order_id -> specimen_id
        # Audit ordering: tie-breaker for events created in the same instant
        self.audit_sequence: int = 0

        self.lock: RLock = RLock()


_store = _Tables()


def store() -> _Tables:
    return _store


def reset_store() -> None:
    global _store
    _store = _Tables()
    from . import clock as _clock
    _clock.clock.reset()
