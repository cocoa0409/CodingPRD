"""In-memory data store with serialised access for first-writer-wins semantics."""
from __future__ import annotations

import threading
from typing import Any, Dict


class Store:
    def __init__(self) -> None:
        self.claimants: Dict[str, Dict[str, Any]] = {}
        self.employers: Dict[str, Dict[str, Any]] = {}
        self.wage_records: Dict[str, Dict[str, Any]] = {}
        self.claims: Dict[str, Dict[str, Any]] = {}
        self.weekly_certifications: Dict[str, Dict[str, Any]] = {}
        self.work_search_entries: Dict[str, Dict[str, Any]] = {}
        self.benefit_payments: Dict[str, Dict[str, Any]] = {}
        self.overpayments: Dict[str, Dict[str, Any]] = {}
        self.appeals: Dict[str, Dict[str, Any]] = {}
        self.employer_charges: Dict[str, Dict[str, Any]] = {}
        self.pandemic_extensions: Dict[str, Dict[str, Any]] = {}

        # Adjudication record per claim (assigned_adjudicator_id, decision_at)
        # Stored on the claim itself for simplicity.

        # Uniqueness helpers
        self.employer_eins: Dict[str, str] = {}  # ein -> employer_id
        # (claim_id, week_ending_date) -> certification_id
        self.cert_unique: Dict[tuple, str] = {}
        # (subject_type, subject_id) -> appeal_id
        self.appeal_unique: Dict[tuple, str] = {}

        # SystemClock — single row
        self.system_clock_now: str = ""  # ISO 8601 datetime; set on first init

        # Coarse-grained lock for serialised mutation
        self.lock = threading.RLock()


_STORE = Store()


def get_store() -> Store:
    return _STORE


def reset_store() -> None:
    """Test-only: wipe all in-memory state."""
    global _STORE
    _STORE = Store()
