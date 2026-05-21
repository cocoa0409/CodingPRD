"""In-memory data store for the Timekeeping & FLSA Overtime API.

A single Store singleton holds the canonical state. All mutating operations
acquire `store.lock` (an RLock) to serialize concurrent writers — this is
how §2.10's first-writer-wins guarantees are realized in-process.
"""
from __future__ import annotations

import threading
import uuid
from typing import Dict


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.employees: Dict[str, dict] = {}
        self.shifts: Dict[str, dict] = {}
        self.punches: Dict[str, dict] = {}
        self.time_edits: Dict[str, dict] = {}
        self.meal_breaks: Dict[str, dict] = {}     # one per shift; keyed by id
        self.detention_events: Dict[str, dict] = {}  # one per shift; keyed by id
        self.tip_declarations: Dict[str, dict] = {}  # one per shift; keyed by id
        self.workweeks: Dict[str, dict] = {}
        self.audit_entries: Dict[str, dict] = {}

        # Indices
        # (shift_id, idempotency_key) -> time_edit_id
        self.time_edit_idempotency_index: Dict[tuple, str] = {}
        # (employee_id, week_start_iso) -> workweek_id
        self.workweek_index: Dict[tuple, str] = {}
        # shift_id -> meal_break_id
        self.shift_meal_break_index: Dict[str, str] = {}
        # shift_id -> detention_event_id
        self.shift_detention_index: Dict[str, str] = {}
        # shift_id -> tip_declaration_id
        self.shift_tip_decl_index: Dict[str, str] = {}

    # Insertion counters (tiebreakers for stable created_at sort).
    _seq_lock = threading.Lock()
    _seq = 0

    def next_seq(self) -> int:
        with Store._seq_lock:
            Store._seq += 1
            return Store._seq


_STORE = Store()


def get_store() -> Store:
    return _STORE
