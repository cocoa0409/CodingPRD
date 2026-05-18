"""In-memory data store + logical clock."""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone


class _Clock:
    """A purely-logical clock that only advances via /_clock/advance.

    PRD §2.11: "the system maintains a single logical server clock that
    is the source of all *_at timestamps and is also the basis for the
    time comparisons in the periodic sweeps. ... advancing the clock by
    itself does not trigger any sweep or any state transition — it only
    makes future server-clock reads return later values."

    We anchor the clock at process start (or after /__test__/reset) and
    advance it by an integer number of seconds via clock.advance(N).
    Each call to now() returns the anchor plus a tiny monotonic
    microsecond tick so successive timestamps within a single request
    are strictly distinguishable for ordering (created_at, updated_at).
    """

    def __init__(self):
        anchor = datetime.now(timezone.utc)
        # Anchor at UTC midnight of "today" so cumulative
        # advance_seconds(N) arithmetic is unambiguous.
        self._logical = datetime(anchor.year, anchor.month, anchor.day, tzinfo=timezone.utc)
        self._tick = 0

    def now(self) -> datetime:
        # Each call gets a fresh microsecond tick — ordering is preserved
        # across writes that happen "at the same logical second", so
        # created_at / updated_at remain monotonic within a single
        # request and the test suite can sort by them deterministically.
        self._tick += 1
        return self._logical + timedelta(microseconds=self._tick)

    def logical_now(self) -> datetime:
        """Tick-free clock for time-comparison checks.

        The microsecond tick on ``now()`` exists purely to disambiguate
        timestamps written in the same second.  It must NOT leak into
        threshold comparisons such as "now >= origination_date + 365
        days" — otherwise a sweep run after exactly N days might miss
        the anniversary because tick(now) < tick(origination).
        """
        return self._logical

    def advance_seconds(self, seconds: int) -> None:
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        self._logical = self._logical + timedelta(seconds=seconds)
        self._tick = 0


class DataStore:
    """In-memory database for every entity in §1.1 plus the logical clock."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = _Clock()

        # Top-level resources (id -> dict).
        self.borrowers: dict[str, dict] = {}
        self.properties: dict[str, dict] = {}
        self.senior_liens: dict[str, dict] = {}
        self.helocs: dict[str, dict] = {}

        # HELOC child resources / ledgers (id -> dict).
        self.draws: dict[str, dict] = {}
        self.payments: dict[str, dict] = {}
        self.rate_resets: dict[str, dict] = {}
        self.fees: dict[str, dict] = {}
        self.default_events: dict[str, dict] = {}

        # Cross-entity audit logs (id -> dict).
        self.insurance_events: dict[str, dict] = {}
        self.senior_lien_default_events: dict[str, dict] = {}
        self.bankruptcy_events: dict[str, dict] = {}

        # ── Sweep idempotency bookkeeping ───────────────────────────
        # billing_sweep_cycle_index: heloc_id -> highest cycle_index processed.
        # The next sweep call advances each eligible HELOC by exactly one cycle.
        self.billing_sweep_cycle_index: dict[str, int] = {}
        # annual_fee_sweep_index: heloc_id -> highest anniversary_index assessed.
        self.annual_fee_sweep_index: dict[str, int] = {}

    def now(self) -> datetime:
        return self.clock.now()

    def logical_now(self) -> datetime:
        return self.clock.logical_now()


store = DataStore()


def reset_store() -> None:
    """Test-only state wipe — recreates every map and rebases the clock."""
    fresh = DataStore()
    with store.lock:
        store.clock = fresh.clock
        store.borrowers.clear()
        store.properties.clear()
        store.senior_liens.clear()
        store.helocs.clear()
        store.draws.clear()
        store.payments.clear()
        store.rate_resets.clear()
        store.fees.clear()
        store.default_events.clear()
        store.insurance_events.clear()
        store.senior_lien_default_events.clear()
        store.bankruptcy_events.clear()
        store.billing_sweep_cycle_index.clear()
        store.annual_fee_sweep_index.clear()
