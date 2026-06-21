"""In-memory data store. Starts empty on every boot. No seeding."""
import uuid
from datetime import datetime, timezone


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def new_id():
    """UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        # One dict per entity type, keyed by id.
        self.crew_members = {}
        self.instruments = {}
        self.survey_orders = {}
        self.research_packets = {}
        self.field_assignments = {}
        self.instrument_reservations = {}
        self.data_sets = {}
        self.plat_drawings = {}
        self.revision_requests = {}
        self.deliverables = {}
        self.invoices = {}

    def insert(self, table, fields):
        """Create a record with common system fields (PRD §2.4)."""
        rid = new_id()
        ts = now_iso()
        rec = dict(fields)
        rec["id"] = rid
        rec["created_at"] = ts
        rec["updated_at"] = ts
        rec["version"] = 1
        table[rid] = rec
        return rec

    def touch(self, rec):
        """Refresh updated_at and bump version on mutation (PRD §2.4)."""
        rec["updated_at"] = now_iso()
        rec["version"] = rec.get("version", 1) + 1
        return rec


store = Store()
