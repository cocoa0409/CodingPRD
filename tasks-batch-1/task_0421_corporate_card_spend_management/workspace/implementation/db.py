"""In-memory data store.

Starts empty on every boot. No seeding. All entities are created via the API.
"""
import itertools
import threading
import uuid

from response import now_iso

# A global lock to keep multi-step mutations atomic for the single-process server.
LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.companies = {}
        self.spend_policies = {}
        self.employees = {}
        self.gl_accounts = {}
        self.cards = {}
        self.transactions = {}
        self.receipts = {}
        self.approval_requests = {}
        self.reimbursement_claims = {}
        self.statements = {}
        self.repayments = {}
        self.reward_accounts = {}
        self.spend_authorizations = {}
        self.erp_sync_batches = {}
        # monotonic ordering counter for stable creation-order sorting
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_create(record):
    """Set system create fields. version starts at 1."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def stamp_create_no_version(record):
    """For Receipt: only id + created_at (immutable, no version/updated_at)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Mark a record mutated: bump version and updated_at."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = now_iso()
    return record
