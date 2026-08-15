"""In-memory data store. State lives only in this process; every start.sh
re-invocation rebuilds it empty. Nothing is seeded at startup."""
import threading
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self.seq = 0
        self.units = {}
        self.beds = {}
        self.demands = {}
        self.requests = {}
        self.staff = {}
        self.audits = {}
        self.supply_items = {}
        self.ledger = {}
        self.outbreaks = {}
        self.notifications = {}
        self.windows = {}
        self.standards = {}
        self.snapshots = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
lock = threading.RLock()
