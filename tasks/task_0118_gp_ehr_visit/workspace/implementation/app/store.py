"""In-memory data store with row tables keyed by id."""
from __future__ import annotations

from threading import RLock
from typing import Any


class _Tables:
    """A bundle of tables holding the system's state."""

    def __init__(self) -> None:
        self.patients: dict[str, dict[str, Any]] = {}
        self.providers: dict[str, dict[str, Any]] = {}
        self.encounters: dict[str, dict[str, Any]] = {}
        self.cpt_line_items: dict[str, dict[str, Any]] = {}
        self.cpt_fee_catalog: dict[str, dict[str, Any]] = {}  # keyed by cpt_code
        self.prescriptions: dict[str, dict[str, Any]] = {}
        self.referrals: dict[str, dict[str, Any]] = {}
        self.portal_messages: dict[str, dict[str, Any]] = {}
        self.hedis_measurements: dict[str, dict[str, Any]] = {}
        self.audit_logs: dict[str, dict[str, Any]] = {}
        # global lock; correctness > throughput
        self.lock: RLock = RLock()


# Module-level singleton; reset_store() rebinds.
_store = _Tables()


def store() -> _Tables:
    return _store


def reset_store() -> None:
    global _store
    _store = _Tables()
    # Also reset the logical clock so each app instance / test boots clean.
    from . import clock as _clock
    _clock.clock.reset()
