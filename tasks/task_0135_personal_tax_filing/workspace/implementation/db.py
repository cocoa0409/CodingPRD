"""In-memory data store + virtual clock (PRD §2.9)."""
from __future__ import annotations

import threading
from datetime import datetime, timezone


class _VirtualClock:
    """Virtual clock per PRD §2.9.

    The clock is logical: advanced only through POST /_clock/advance.
    Each call to now() returns a strictly monotonically increasing
    datetime so created_at / updated_at remain distinguishable, but
    the visible second-resolution "instant" only changes when
    advance_to() is called.

    Internal representation:
      _logical: the externally-visible UTC instant (set on construction
                or via advance_to)
      _tick:    monotonic microsecond bump applied to each now() read,
                guaranteeing strict ordering of timestamps even when
                multiple events occur "at" the same logical instant.
    """

    def __init__(self):
        # Anchor at a fixed early epoch so the clock can always be
        # advanced forward to any test-chosen instant. PRD §2.9 frames
        # advance as moving "to a supplied future instant" — there is
        # no PRD-stated starting wall-time, and the clock must be a
        # deterministic test-controlled handle, so the safe default is
        # an epoch far in the past.
        self._logical = datetime(2000, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        self._tick = 0

    def now(self) -> datetime:
        """Strictly monotonic clock read.

        Returns _logical + microsecond bump so that callers stamping
        created_at/updated_at always see strictly increasing values.
        """
        self._tick += 1
        # micro stays in 0..999_999 so the ISO ms field stays valid.
        micro = self._tick % 1_000_000
        return self._logical.replace(microsecond=micro)

    def advance_to(self, target: datetime) -> datetime:
        """Advance the logical clock to `target` (no-op if target is in
        the past). Returns the new logical instant. Caller must hold
        store.lock for atomicity with cascaded transitions."""
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        else:
            target = target.astimezone(timezone.utc)
        # Truncate the visible instant to second resolution so it
        # round-trips cleanly through ISO formatting.
        target = target.replace(microsecond=0)
        if target > self._logical:
            self._logical = target
            self._tick = 0
        return self._logical

    @property
    def logical(self) -> datetime:
        """The externally-visible (second-resolution) clock instant."""
        return self._logical


class DataStore:
    """In-memory database for all entities + the virtual clock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _VirtualClock()

        # Each map: id -> dict
        self.taxpayers = {}
        self.tax_returns = {}
        self.income_documents = {}
        self.schedules = {}
        self.tax_credits = {}
        self.efilings = {}
        self.amendments = {}
        self.estimated_payments = {}
        self.audit_logs = []  # append-only list of AuditLog entries

    def now(self) -> datetime:
        """Strictly monotonic clock read for created_at/updated_at."""
        return self.clock.now()

    def clock_now(self) -> datetime:
        """The externally-visible virtual clock instant (advance_to value)."""
        return self.clock.logical

    def reset(self) -> None:
        """Wipe all in-memory state and re-anchor the virtual clock.

        Test-only helper. Used by /__test__/reset to give each test a
        clean slate (the PRD's virtual clock advances forward only, so
        without a hard reset the clock would accumulate across tests
        and reject otherwise-valid future-dated payment dates).
        """
        with self.lock:
            self.taxpayers.clear()
            self.tax_returns.clear()
            self.income_documents.clear()
            self.schedules.clear()
            self.tax_credits.clear()
            self.efilings.clear()
            self.amendments.clear()
            self.estimated_payments.clear()
            self.audit_logs.clear()
            self.clock = _VirtualClock()


# Singleton store used throughout the app.
store = DataStore()
