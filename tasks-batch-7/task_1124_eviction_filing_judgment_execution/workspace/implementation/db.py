"""In-memory data store. The store starts empty on every boot — no seeding."""
import threading
import uuid
from datetime import datetime, timezone

LOCK = threading.RLock()


class Store:
    def __init__(self):
        self.landlords = {}
        self.units = {}
        self.tenancies = {}
        self.cases = {}
        self.notices = {}
        self.packages = {}
        self.service_attempts = {}
        self.hearings = {}
        self.answers = {}
        self.referrals = {}
        self.judgments = {}
        self.writs = {}
        self.storage_records = {}
        self.collection_entries = {}
        self.reports = {}
        self.seq = 0          # global insertion sequence (tiebreak for created_at)
        self.case_seq = 0     # EV-<year>-<seq> counter
        self.report_seq = 0   # RHR-<seq> counter
        # Logical clock: starts at exactly 2026-05-01T00:00:00Z, never wall clock.
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


STORE = Store()


def now():
    return STORE.clock


def new_id():
    return str(uuid.uuid4())


def new_record(fields):
    """Common-fields resource: id, created_at, updated_at, version."""
    STORE.seq += 1
    t = now()
    r = dict(fields)
    r["id"] = new_id()
    r["created_at"] = t
    r["updated_at"] = t
    r["version"] = 1
    r["_seq"] = STORE.seq
    return r


def new_ledger(fields):
    """Immutable ledger record (ServiceAttempt / CollectionEntry): id + created_at only."""
    STORE.seq += 1
    r = dict(fields)
    r["id"] = new_id()
    r["created_at"] = now()
    r["_seq"] = STORE.seq
    return r


def bump(r):
    """Refresh updated_at and increment version on a mutated common-fields entity."""
    r["updated_at"] = now()
    r["version"] += 1


def sorted_items(d):
    return sorted(d.values(), key=lambda r: (r["created_at"], r["_seq"]))
