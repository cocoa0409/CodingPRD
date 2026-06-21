"""In-memory data store. Starts empty on every boot. No seeding."""
import itertools
import threading
import uuid
from datetime import datetime, timezone

# Global write lock to keep each request's cascade atomic and serialized.
LOCK = threading.RLock()

# Monotonic counter to break created_at ties deterministically (sequence order).
_seq = itertools.count(1)

# One dict per entity type, keyed by id.
grantors = {}
trustees = {}
beneficiaries = {}
trusts = {}
trustee_appointments = {}
accounts = {}
receipts = {}
disbursements = {}
distributions = {}
k1s = {}
filings = {}
gst_allocations = {}
gst_events = {}


def new_id():
    # Server-minted UUID with no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def next_seq():
    return next(_seq)


def base_fields():
    """The system-managed quartet plus an internal monotonic sequence."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """Refresh updated_at and bump version (PRD §2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1
