"""In-memory data store.

Every collection is a plain dict keyed by id. The store starts EMPTY on every
process boot — nothing is seeded, preloaded, or hardcoded. The test harness
restarts the server before each test, so a fresh process wipes all state.
"""
from __future__ import annotations

import datetime
import uuid


class DB:
    def __init__(self) -> None:
        self.parts: dict = {}
        self.vehicles: dict = {}
        self.fitments: dict = {}
        self.cross_references: dict = {}
        self.price_tiers: dict = {}
        self.accounts: dict = {}
        self.sales_orders: dict = {}
        self.order_lines: dict = {}
        self.core_returns: dict = {}
        self.warranty_claims: dict = {}
        self.reorder_requests: dict = {}
        self.drivers: dict = {}
        self.bays: dict = {}
        self.delivery_runs: dict = {}
        # monotonically increasing sequence to break created_at ties for sorting
        self._seq = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


db = DB()


def new_id() -> str:
    """A UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    dt = datetime.datetime.now(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
