"""In-memory data store + logical clock. No disk persistence, no seeding."""
import threading
import uuid
from datetime import datetime, timezone

# Logical clock startup value per PRD section 2.7 (never falls back to wall clock).
START_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.programs = {}
        self.pools = {}
        self.rates = {}
        self.criteria = {}
        self.applicants = {}
        self.applications = {}
        self.contracts = {}
        self.items = {}
        self.payment_requests = {}
        self.advances = {}
        self.modifications = {}
        self.spot_checks = {}
        self.obligations = {}
        self.demands = {}
        self.seq = 0  # global creation counter -> deterministic created_at ordering
        self.clock = START_CLOCK

    def next_seq(self):
        self.seq += 1
        return self.seq


STORE = Store()
LOCK = threading.RLock()


def new_id():
    return str(uuid.uuid4())


def now():
    return STORE.clock
