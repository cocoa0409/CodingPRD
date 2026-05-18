"""In-memory data store with logical clock."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Entity tables (keyed by id)
        self.cardholders: dict = {}
        self.accounts: dict = {}
        self.cashback_categories: dict = {}
        self.quarterly_activations: dict = {}
        self.transactions: dict = {}
        self.transfer_partners: dict = {}
        self.points_transfers: dict = {}
        self.statement_credits: dict = {}
        self.points_ledger: dict = {}

        # Indexes
        self.cardholder_emails: set = set()
        self.category_codes: set = set()
        self.partner_codes: set = set()
        # uniqueness on (account_id, category_id, quarter_label) for activations
        self.activation_uniq: set = set()

        # Logical simulated clock; tests will advance via /_clock/advance.
        self._clock: datetime = datetime.now(timezone.utc)

        # Global mutex for serializing mutations (concurrency control).
        self.lock = threading.RLock()

        # Monotonic insertion counter used to break ties when two ledger
        # entries share the same `occurred_at` (likely when the simulated
        # clock has not advanced between appends).
        self._ledger_seq: int = 0

    def next_ledger_seq(self) -> int:
        self._ledger_seq += 1
        return self._ledger_seq

    # ---- clock ----
    @property
    def clock(self) -> datetime:
        return self._clock

    def set_clock(self, dt: datetime) -> None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        self._clock = dt.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._clock

    def now_iso(self) -> str:
        n = self._clock
        return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"

    # ---- ids ----
    def new_id(self) -> str:
        return str(uuid.uuid4())


store = Store()
