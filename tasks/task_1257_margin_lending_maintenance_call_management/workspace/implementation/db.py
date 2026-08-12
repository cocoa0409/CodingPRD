"""In-memory data store and the server-held logical clock.

Storage is in-memory only (Python dicts keyed by id). The store starts empty
on every boot; no entity is ever seeded, preloaded, or hardcoded at startup.

PRD 2.5: before it is ever set, the logical clock reads exactly
2026-05-01T00:00:00Z and never falls back to wall-clock time.
"""
import itertools
import threading
from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clock = CLOCK_DEFAULT
        # Insertion sequence used to break created_at ties deterministically
        # (many entities share a logical-clock instant).
        self.seq = itertools.count(1)
        # Primary resources (common fields: id/created_at/updated_at/version)
        self.customers = {}
        self.applications = {}
        self.accounts = {}
        self.securities = {}
        self.positions = {}
        self.calls = {}
        self.liquidation_orders = {}
        self.cash_movements = {}
        self.rate_tiers = {}
        self.disputes = {}
        # Ledger-style records (immutable; id/created_at only)
        self.fills = {}
        self.day_trade_events = {}
        self.marks = {}
        self.interest_entries = {}
        # Secondary index: (account_id, security_id) -> position id
        self.position_by_pair = {}


store = Store()

COLLECTIONS = [
    "customers", "applications", "accounts", "securities", "positions",
    "calls", "liquidation_orders", "cash_movements", "rate_tiers",
    "disputes", "fills", "day_trade_events", "marks", "interest_entries",
]
