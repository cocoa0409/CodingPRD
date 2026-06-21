import threading
import uuid

from clock import Clock


class DB:
    """In-memory data store. Starts EMPTY on every boot — no seeding."""

    def __init__(self):
        self.lock = threading.RLock()
        self.clock = Clock()
        self.facilities = {}
        self.units = {}
        self.tenants = {}
        self.leases = {}
        self.invoices = {}
        self.payments = {}
        self.ledger_entries = {}
        self.insurance_policies = {}
        self.auction_proceedings = {}
        self.transfer_orders = {}
        # monotonic sequence to enforce a stable created_at tie-break that
        # survives identical-timestamp clock writes
        self._seq = 0

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()
