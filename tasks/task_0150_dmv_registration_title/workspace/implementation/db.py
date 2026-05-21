"""In-memory data store.

All entities are dicts keyed by UUID. A single RLock serialises mutations
so racing transitions resolve deterministically (first-writer-wins on the
contested key/state per SCAFFOLD §1.2.1 concurrency rules).

The logical server clock lives here too — POST /_clock/advance moves it.
"""

import threading
from datetime import datetime, timezone


class Store:
    def __init__(self) -> None:
        # Entity tables — all keyed by id
        self.owners: dict[str, dict] = {}
        self.vehicles: dict[str, dict] = {}
        self.titles: dict[str, dict] = {}
        self.lien_records: dict[str, dict] = {}
        self.emissions_inspections: dict[str, dict] = {}
        self.real_id_applications: dict[str, dict] = {}
        self.plates: dict[str, dict] = {}
        self.transfer_applications: dict[str, dict] = {}
        # Append-only ledger
        self.fee_ledger: list[dict] = []
        # Tracks which X-User-ID ran assess-fees on each TransferApplication
        # so segregation-of-duties can compare against issue-plate caller.
        self.assess_fees_actor: dict[str, str] = {}

        # Logical server clock; defaults to real UTC at startup.
        self._clock: datetime = datetime.now(tz=timezone.utc)

        # Global lock; light workload, simple serialisation across all entities.
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
