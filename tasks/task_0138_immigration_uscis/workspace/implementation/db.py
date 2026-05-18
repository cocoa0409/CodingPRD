"""In-memory data store and logical clock for the USCIS API.

The clock is intentionally a logical clock advanced only by /_clock/advance.
PRD §3.10 specifies that the action accepts a `to` ISO 8601 UTC timestamp
to which the server clock is set. Between advances, each call to now()
returns the same logical instant + a monotonic microsecond tick so that
ordering between created_at / updated_at values is still strictly
preserved within a single advance window.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone


class _Clock:
    """Logical clock anchored at process start; advanced only by /_clock/advance."""

    def __init__(self):
        # Anchor at real wall time at startup. PRD does not pin the initial
        # value beyond "the current server clock"; tests advance it as needed.
        self._logical = datetime.now(timezone.utc)
        self._tick = 0

    def now(self) -> datetime:
        """Return the logical clock + a monotonic microsecond tick for ordering."""
        self._tick += 1
        # Note: we do NOT bump the underlying _logical with the tick — only
        # add it on read. Comparisons that check "now() > deadline" use the
        # underlying logical instant (we add a single µs tick that is small
        # compared to second-level deadlines, but for absolute precision we
        # use logical_now() in comparisons that hinge on equality vs strict
        # inequality).
        from datetime import timedelta
        return self._logical + timedelta(microseconds=self._tick)

    def logical_now(self) -> datetime:
        """The wall-time-stable logical instant (no microsecond tick)."""
        return self._logical

    def set_to(self, dt: datetime) -> None:
        """Set the clock to the supplied UTC instant. Used by /_clock/advance."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._logical = dt.astimezone(timezone.utc)
        self._tick = 0


class DataStore:
    """In-memory store for every entity in the SCAFFOLD."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _Clock()

        # Per-entity dictionaries: id -> dict
        self.petitioners: dict[str, dict] = {}
        self.beneficiaries: dict[str, dict] = {}
        self.case_type_configs: dict[str, dict] = {}  # id-keyed
        self.case_type_configs_by_type: dict[str, dict] = {}  # case_type-keyed view
        self.cases: dict[str, dict] = {}
        self.biometrics: dict[str, dict] = {}
        self.rfes: dict[str, dict] = {}
        self.interviews: dict[str, dict] = {}
        self.visa_bulletins: dict[str, dict] = {}
        self.case_events: dict[str, dict] = {}

        # System config — single row.
        self.chart_in_effect = "FINAL_ACTION"

        # Monotonic sequence keyed by (receipt_prefix, fiscal_year) — see
        # services/receipt.py for the minting algorithm.
        self.receipt_sequences: dict[tuple[str, int], int] = {}

        # Globally-unique receipt numbers (for collision detection).
        self.receipt_numbers: set[str] = set()

    def now(self) -> datetime:
        return self.clock.now()


# Singleton store used throughout the app.
store = DataStore()
