"""In-memory data store. Starts empty on every boot. No seeding."""
import threading
import uuid

from response import now_iso


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.clients = {}
        self.linguists = {}
        self.rate_cards = {}
        self.projects = {}
        self.jobs = {}
        self.assignments = {}
        self.qa_reports = {}
        self.invoices = {}
        self.payout_ledger = {}
        self.certificates = {}

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


def new_id():
    return db.new_id()


def common_fields(initial_version=1):
    """System-managed fields for full-lifecycle entities: id, created_at, updated_at, version."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": initial_version,
    }


def lean_fields():
    """Lean entities (RateCard, PayoutLedgerEntry): only id + created_at."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
    }


def touch(entity):
    """Refresh updated_at and increment version on mutation."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity["version"] + 1
