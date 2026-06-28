"""In-memory data store (PRD §2.4).

All state lives in process memory only. Nothing is persisted to disk, and
NOTHING is seeded at import or startup. Every entity is created by an API call.
A fresh process therefore boots with empty collections.
"""
import uuid
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        # Audit-tracked entities (id, created_at, updated_at, version).
        self.members = {}
        self.equipment = {}
        self.spray_rooms = {}
        self.sessions = {}
        self.products = {}
        self.retail_orders = {}
        self.salon_ledger = None  # singleton, lazily created on first need

        # Write-once records (id, created_at only).
        self.membership_plans = {}
        self.consents = {}
        self.payments = {}
        self.maintenance_logs = {}

        # Billing simulator pinned outcomes for next upgrade, keyed by member id.
        self.upgrade_outcomes = {}

        # Monotonic sequence to break created_at ties deterministically.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


store = Store()
