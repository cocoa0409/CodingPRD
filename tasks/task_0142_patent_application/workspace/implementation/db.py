"""In-memory data store.

All entities are stored in plain dictionaries keyed by UUID. A single
RLock serialises mutations so racing transitions resolve deterministically
(first-writer-wins on the contested key/state per SCAFFOLD §1.2.1).

The SystemClock is held here too: tests advance it via POST /_clock/advance.
"""

import threading
from datetime import datetime, timezone


class Store:
    def __init__(self) -> None:
        # Entity tables
        self.applicants: dict[str, dict] = {}
        self.applications: dict[str, dict] = {}
        self.office_actions: dict[str, dict] = {}
        self.responses: dict[str, dict] = {}
        self.fee_transactions: dict[str, dict] = {}
        self.maintenance_fees: dict[str, dict] = {}
        self.pct_phases: dict[str, dict] = {}
        self.audit_events: list[dict] = []

        # Idempotency cache: (route, key, applicant_id) -> {payload_fingerprint, response_body, http_status, created_at}
        self.idempotency_cache: dict[tuple, dict] = {}

        # Logical server clock — defaults to real UTC at startup.
        self._clock: datetime = datetime.now(tz=timezone.utc)

        # Single global lock; the API workload is light and this gives
        # straightforward serialisation across all entities.
        self.lock = threading.RLock()

    # ------------------------------------------------------------------
    # Clock helpers
    # ------------------------------------------------------------------
    def now(self) -> datetime:
        return self._clock

    def set_clock(self, when: datetime) -> None:
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        self._clock = when.astimezone(timezone.utc)


store = Store()
