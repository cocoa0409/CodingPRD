"""In-memory data store. All entities live here."""

import threading
import uuid


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.sellers = {}
        self.buyers = {}
        self.vehicles = {}
        self.assessments = {}
        self.listings = {}
        self.bids = {}
        self.reservations = {}
        self.purchase_orders = {}
        self.transfers = {}
        self.loans = {}
        self.warranties = {}
        self.warranty_claims = {}
        self.disputes = {}
        self.events = {}              # id -> event
        self.events_by_key = {}       # idempotency_key -> event
        self.audit_logs = []          # list, append-only

    def reset(self):
        with self.lock:
            self.__init__()


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    """Generate a request id starting with 'req_' followed by alphanumerics."""
    raw = uuid.uuid4().hex.upper()
    return "req_" + raw  # 36 chars total, matches req_RANDOMALPHANUM... shape


DB_INSTANCE = DB()
