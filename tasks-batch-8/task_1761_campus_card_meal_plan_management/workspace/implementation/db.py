"""In-memory data store. Fresh per process; the per-test-server isolation
model means every start.sh invocation begins with completely empty state."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.holders = {}
        self.cards = {}
        self.photos = {}
        self.terms = {}
        self.plans = {}
        self.enrollments = {}
        self.change_requests = {}
        self.accounts = {}
        self.ledger_entries = {}
        self.transactions = {}
        self.disputes = {}
        self.refund_requests = {}
        self.zones = {}
        self.grants = {}
        self.access_events = {}
        self.merchants = {}
        self.settlements = {}
        # idempotency key -> {payload, status, data}
        self.idempotency = {}
        # Logical clock: server startup default, never falls back to wall clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        # Global monotonic counter for stable ordering tie-breaks.
        self.seq = 0
        self.used_card_numbers = set()

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
