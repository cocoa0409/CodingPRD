"""In-memory data store. Starts empty on every boot; no seeding."""
import threading
from datetime import datetime, timezone

# Logical clock startup default: exactly 2026-08-01T00:00:00Z (PRD 2.4).
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0  # global monotonically increasing creation sequence
        self.clock = CLOCK_DEFAULT
        self.associations = {}
        self.borrowers = {}
        self.loans = {}
        self.budgets = {}
        self.collaterals = {}
        self.filings = {}
        self.policies = {}
        self.claims = {}
        self.draws = {}
        self.repayments = {}
        self.covenants = {}
        self.plans = {}
        self.deferrals = {}
        self.distributions = {}
        self.notices = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


STORE = Store()


def get_clock():
    return STORE.clock


def set_clock(dt):
    STORE.clock = dt
