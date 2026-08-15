"""In-memory data store and logical clock.

The store starts empty on every boot. No entity seeding happens here or
anywhere else at startup -- every entity is created via the declared API.
"""

import itertools
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Entity tables keyed by id. Values are plain dicts.
        self.programs = {}
        self.members = {}
        self.cards = {}
        self.ledger = {}          # HourBankLedger entries (append-only)
        self.aircraft = {}
        self.trips = {}
        self.legs = {}
        self.invoices = {}
        self.peak_windows = {}
        self.blackout_windows = {}
        self.escrow_accounts = {}
        self.refunds = {}
        self.upgrades = {}

        # Monotonic insertion sequence for stable created_at tie-breaking.
        self.seq = itertools.count(1)

        # Logical clock: starts at 2026-05-01T00:00:00Z per PRD section 2.10.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self.clock

    def next_seq(self):
        return next(self.seq)


# Module-level singleton. A fresh process gets a fresh, empty store.
db = Store()
