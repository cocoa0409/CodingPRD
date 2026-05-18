"""In-memory data store.

All entities are stored in dictionaries keyed by their UUID id. A single
threading.Lock serializes mutations so racing operations resolve deterministically
(first-writer-wins on the contested key/state per the scaffold concurrency rules).

Server clock state is also held here so the test-only /_clock/advance endpoint
can move "now" forward without wall-clock waits.
"""

import threading
from datetime import datetime, timezone


class Store:
    def __init__(self) -> None:
        self.debtors: dict[str, dict] = {}
        self.creditors: dict[str, dict] = {}
        self.cases: dict[str, dict] = {}
        self.schedules: dict[str, dict] = {}
        self.means_test_results: dict[str, dict] = {}
        self.claims: dict[str, dict] = {}
        self.plans: dict[str, dict] = {}
        self.trustee_payments: dict[str, dict] = {}
        self.collection_actions: dict[str, dict] = {}

        # Logical server clock; defaults to real UTC at startup. Tests may
        # advance this via POST /_clock/advance.
        self._clock: datetime = datetime.now(tz=timezone.utc)

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
