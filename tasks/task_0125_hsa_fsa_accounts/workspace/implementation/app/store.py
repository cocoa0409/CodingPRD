"""In-memory data store. Holds all entity collections, clock, and provides UUID minting."""
from __future__ import annotations

import threading
import uuid

from .clock import LogicalClock


class DataStore:
    """A single in-memory store holding every collection plus the logical clock."""

    def __init__(self) -> None:
        # Mutating mutex for write paths.
        self.lock = threading.RLock()
        self.clock = LogicalClock()

        # Primary collections keyed by id.
        self.account_holders: dict[str, dict] = {}
        self.accounts: dict[str, dict] = {}
        self.plan_years: dict[str, dict] = {}
        self.dependents: dict[str, dict] = {}
        self.contributions: dict[str, dict] = {}
        self.qualified_expenses_by_id: dict[str, dict] = {}
        self.qualified_expenses_by_code: dict[str, dict] = {}
        self.claims: dict[str, dict] = {}
        self.audit_events: list[dict] = []
        self.ops_runs: list[dict] = []

        # Append order counter (monotonic), used as a stable tiebreaker
        # and as the insertion order for append-only tables.
        self._seq = 0

        # OpsRun.index counter — first run is 1.
        self._ops_run_index = 0

    # ----- Identity & sequencing ----- #

    def new_id(self) -> str:
        # UUID4 with no type prefix per PRD §2.4.
        return str(uuid.uuid4())

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def next_ops_index(self) -> int:
        self._ops_run_index += 1
        return self._ops_run_index

    def reset(self) -> None:
        """Wipe every collection AND the logical clock in place. Used by
        the test harness via /__test__/reset between tests."""
        with self.lock:
            self.clock = LogicalClock()
            self.account_holders.clear()
            self.accounts.clear()
            self.plan_years.clear()
            self.dependents.clear()
            self.contributions.clear()
            self.qualified_expenses_by_id.clear()
            self.qualified_expenses_by_code.clear()
            self.claims.clear()
            self.audit_events.clear()
            self.ops_runs.clear()
            self._seq = 0
            self._ops_run_index = 0


# Singleton store instance used across the app.
store = DataStore()
