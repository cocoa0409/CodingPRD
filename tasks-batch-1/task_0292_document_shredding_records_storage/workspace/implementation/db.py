"""In-memory data store. All state lives in process memory and is wiped on
every fresh boot (per-test-server isolation re-launches the process).

NO seeding, preloading, or hardcoded entities. Every entity is created via the
declared API surface.
"""
import threading
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        # Each entity type keyed by id -> dict.
        self.accounts = {}
        self.locations = {}
        self.rate_cards = {}
        self.containers = {}
        self.service_orders = {}
        self.weight_tickets = {}
        self.custody_events = {}
        self.certificates = {}
        self.destruction_invoices = {}
        self.retention_boxes = {}
        self.retrieval_requests = {}
        self.compliance_holds = {}
        self.storage_invoices = {}
        # Monotonic insertion counter for stable ordering ties.
        self._seq = 0
        self.lock = threading.RLock()

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_id():
    # Server-minted UUID with no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def now_iso():
    # ISO 8601 UTC timestamp with three fractional digits (PRD §2.4).
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def stamp_create(entity, with_version=True):
    """Set system-managed common fields on creation (PRD §2.4)."""
    entity["id"] = new_id()
    ts = now_iso()
    entity["created_at"] = ts
    entity["_seq"] = db.next_seq()  # insertion order tiebreaker, not exposed
    if with_version:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and increment version on mutation (PRD §2.4 / §2.5)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 0) + 1
