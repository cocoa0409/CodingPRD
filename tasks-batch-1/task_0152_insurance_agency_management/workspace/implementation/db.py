"""In-memory data store.

ALL state is held in plain Python dicts keyed by id. There is NO disk
persistence and NO startup seeding: the store boots empty on every process
launch, exactly as the per-test-server harness requires. Tests construct every
entity they need through the declared API surface.

Insertion order is preserved (Python 3.7+ dict ordering), which we rely on for
the PRD §2.3 "sort by created_at ascending (oldest first)" list ordering, since
ids are created monotonically within a process.
"""
import itertools
import threading
import uuid

from response import now_iso


class Store:
    def __init__(self):
        self._lock = threading.RLock()
        # One dict per entity collection. All start empty.
        self.carriers = {}
        self.products = {}
        self.producers = {}
        self.licenses = {}
        self.appointments = {}
        self.accounts = {}
        self.policies = {}
        self.commission_splits = {}
        self.trust_accounts = {}
        self.trust_ledger_entries = {}
        self.commission_statements = {}
        self.renewal_tasks = {}
        # Monotonic sequence to give a stable created ordering even if two
        # records land in the same millisecond timestamp.
        self._seq = itertools.count(1)

    @property
    def lock(self):
        return self._lock

    def new_id(self):
        # UUID with no type prefix (PRD §2.4).
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)


# Module-level singleton store. Importing this module does NOT populate it.
store = Store()


def new_common(extra_quartet=True):
    """Build the system/common fields for a fresh entity.

    extra_quartet=True -> id, created_at, updated_at, version (the full quartet
    PRD §2.4 gives to most entities).
    extra_quartet=False -> id, created_at only (TrustLedgerEntry is immutable).
    """
    ts = now_iso()
    base = {
        "id": store.new_id(),
        "created_at": ts,
        "_seq": store.next_seq(),
    }
    if extra_quartet:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def touch(rec):
    """Apply a mutation: bump version by one and refresh updated_at (PRD §2.4)."""
    rec["version"] = rec.get("version", 0) + 1
    rec["updated_at"] = now_iso()
