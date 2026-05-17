"""In-memory data store with row tables keyed by id."""
from __future__ import annotations

from threading import RLock
from typing import Any


class _Tables:
    """A bundle of tables holding the system's state."""

    def __init__(self) -> None:
        self.patients: dict[str, dict[str, Any]] = {}
        self.therapists: dict[str, dict[str, Any]] = {}
        self.episodes: dict[str, dict[str, Any]] = {}
        self.evaluations: dict[str, dict[str, Any]] = {}
        self.plan_of_cares: dict[str, dict[str, Any]] = {}
        self.authorizations: dict[str, dict[str, Any]] = {}
        self.visits: dict[str, dict[str, Any]] = {}
        self.home_exercise_programs: dict[str, dict[str, Any]] = {}
        self.mips_measures: dict[str, dict[str, Any]] = {}
        self.discharge_assessments: dict[str, dict[str, Any]] = {}
        self.veteran_referrals: dict[str, dict[str, Any]] = {}
        # uniqueness indexes
        self.npi_index: dict[str, str] = {}
        # global lock; correctness > throughput
        self.lock: RLock = RLock()


_store = _Tables()


def store() -> _Tables:
    return _store


def reset_store() -> None:
    global _store
    _store = _Tables()
    from . import clock as _clock
    _clock.clock.reset()
