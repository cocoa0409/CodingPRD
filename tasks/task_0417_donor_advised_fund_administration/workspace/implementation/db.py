"""In-memory data store.

Per the implementation contract: storage is in-memory ONLY (plain Python dicts
keyed by id). The store starts EMPTY on every process boot — nothing is seeded,
preloaded, or hardcoded. start.sh re-invocation creates a fresh process and so
wipes every byte of state. No SQLite, no JSON dump, no /tmp cache.
"""
import datetime
import itertools
import threading
import uuid

# A single coarse lock to keep multi-step mutating operations atomic
# (PRD 2.8: state changes that touch more than one resource apply every effect
# atomically; PRD 2.9 OCC; cascades).
LOCK = threading.RLock()

# Monotonic counter for sponsor-minted sequential substantiation receipt numbers
# (PRD 3.3: "a sponsor-minted sequential receipt_number").
_receipt_seq = itertools.count(1)

# Monotonic counter giving each entity a stable creation order for ties (used for
# created_at-ascending list sort and for tie-breaks where created_at is equal).
_create_seq = itertools.count(1)


class Store:
    """Holds every entity collection keyed by id."""

    def __init__(self):
        self.sponsors = {}
        self.pools = {}
        self.nav_periods = {}
        self.charities = {}
        self.accounts = {}
        self.contributions = {}
        self.receipts = {}
        self.allocations = {}
        self.grants = {}
        self.succession_plans = {}
        self.rebalance_orders = {}
        self.ledger_entries = {}


db = Store()


def new_id():
    """Server-minted id: a UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (PRD 2.4)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def next_seq():
    return next(_create_seq)


def next_receipt_number():
    return str(next(_receipt_seq))


def common_create_fields():
    """id/created_at/updated_at/version for full-lifecycle resources (PRD 2.4)."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def audit_create_fields():
    """id/created_at ONLY for append-only audit records (PRD 2.4):
    SubstantiationReceipt and LedgerEntry have no updated_at and no version."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }


def touch(entity):
    """Refresh updated_at and bump version on a full-lifecycle resource (PRD 2.4/2.8)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
