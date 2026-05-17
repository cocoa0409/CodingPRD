"""In-memory data store with row tables keyed by id."""
from __future__ import annotations

from threading import RLock
from typing import Any


class _Tables:
    """Bundle of tables holding the system's state."""

    def __init__(self) -> None:
        self.therapists: dict[str, dict[str, Any]] = {}
        self.state_licenses: dict[str, dict[str, Any]] = {}
        self.supervisors: dict[str, dict[str, Any]] = {}
        self.supervision_assignments: dict[str, dict[str, Any]] = {}
        self.patients: dict[str, dict[str, Any]] = {}
        self.insurance_plans: dict[str, dict[str, Any]] = {}
        self.appointments: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.crisis_assessments: dict[str, dict[str, Any]] = {}
        self.safety_plans: dict[str, dict[str, Any]] = {}
        self.billing_claims: dict[str, dict[str, Any]] = {}
        # Global serialization lock — correctness over throughput.
        self.lock: RLock = RLock()


_store = _Tables()


def store() -> _Tables:
    return _store


def reset_store() -> None:
    global _store
    _store = _Tables()
    from . import clock as _clock
    _clock.clock.reset()
