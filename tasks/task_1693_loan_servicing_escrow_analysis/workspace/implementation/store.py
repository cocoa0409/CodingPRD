"""In-memory data store. Fresh per process; no seeding."""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.loans = {}
        self.accounts = {}
        self.ledger_entries = {}
        self.line_items = {}
        self.payees = {}
        self.disbursements = {}
        self.policies = {}
        self.tax_records = {}
        self.analyses = {}
        self.notices = {}
        self.advances = {}
        self.error_cases = {}
        # Logical clock: exactly 2026-08-01T00:00:00Z before any set call.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
