"""In-memory data store.

All state lives in module-level dicts. A fresh process boots with empty
dicts — no seeding. The logical clock starts at 2026-05-01T00:00:00Z and
is advanced only via POST /_clock/set_current_utc.
"""

import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.clients = {}
        self.entitlements = {}
        self.accounts = {}
        self.ledger_entries = {}  # id -> entry; also keep per-account order via list
        self.ledger_order = []    # global insertion order list of ids
        self.budget_plans = {}
        self.disbursements = {}
        self.deposits = {}
        self.court_orders = {}
        self.bonds = {}
        self.reports = {}
        self.spend_down_plans = {}
        self.audit_cases = {}
        self.conservators = {}
        # Logical clock: datetime with tzinfo=UTC
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.lock = threading.RLock()


store = Store()
