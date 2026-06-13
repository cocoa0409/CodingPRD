"""In-memory data store.

Every dict is keyed by the entity's server-minted UUID id. The store is
populated exclusively through the API surface — nothing is seeded at boot, so a
fresh process always starts with completely empty state.
"""
import threading
import uuid
from datetime import datetime, timezone


class Clock:
    """Server logical clock, drivable via POST /_clock/set_current_utc."""

    def __init__(self):
        self._override = None  # a datetime (UTC) or None for wall-clock

    def now(self):
        if self._override is not None:
            return self._override
        return datetime.now(timezone.utc)

    def set(self, dt):
        self._override = dt


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = Clock()
        self.consignors = {}
        self.markdown_schedules = {}
        self.agreements = {}
        self.intake_batches = {}
        self.items = {}
        self.authentication_reviews = {}
        self.sales = {}
        self.sale_lines = {}
        self.payout_ledger_entries = {}
        self.store_credit_transactions = {}
        self.settlements = {}
        self.donation_records = {}
        # monotonic creation sequence so list ordering by created_at is stable
        # even when two records share the same millisecond timestamp.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    return str(uuid.uuid4())


# Single global store instance. Created fresh on every process boot.
store = Store()
