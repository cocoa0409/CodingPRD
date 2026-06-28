"""In-memory data store. State is wiped on every process boot."""
import uuid
from datetime import datetime, timezone

# Default logical clock at startup (PRD §2.10).
DEFAULT_CLOCK = "2026-04-01T00:00:00Z"


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.clients = {}
        self.contracts = {}
        self.design_proposals = {}
        self.proposal_line_items = {}
        self.inventory_items = {}
        self.crews = {}
        self.work_orders = {}
        self.visits = {}
        self.storage_bays = {}
        self.storage_lots = {}
        self.damage_reports = {}
        self.restock_orders = {}
        self.renewal_offers = {}
        # Logical clock (string ISO instant).
        self.clock = DEFAULT_CLOCK
        # monotonic creation counter for deterministic created_at tie-breaks
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def reset():
    global db
    db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def base_fields():
    """id/created_at/updated_at/version quartet (PRD §2.4)."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(record):
    """Refresh updated_at and increment version on mutation (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def public(record):
    """Strip internal-only fields before serialization."""
    return {k: v for k, v in record.items() if not k.startswith("_")}
