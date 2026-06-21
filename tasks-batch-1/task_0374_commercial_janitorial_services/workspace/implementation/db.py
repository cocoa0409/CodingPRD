"""In-memory data store. All state lives in process memory only; a fresh
process boots with empty collections. No seeding, no persistence."""
import uuid
from datetime import datetime, timezone


def _now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.accounts = {}
        self.sites = {}
        self.contracts = {}
        self.schedules = {}
        self.crew = {}
        self.visits = {}
        self.time_entries = {}
        self.inspections = {}
        self.periodic_jobs = {}
        self.complaints = {}
        self.billing_periods = {}
        self.invoice_lines = {}
        self.supply_orders = {}
        # Monotonic counter to break created_at timestamp ties deterministically.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


def now_iso():
    return _now_iso()


def new_common(with_version=True):
    """Common system fields for a freshly created entity."""
    ts = _now_iso()
    base = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "_seq": db.next_seq(),
    }
    if with_version:
        base["version"] = 1
    return base


def touch(entity):
    """Refresh updated_at and bump version on a mutation."""
    entity["updated_at"] = _now_iso()
    if "version" in entity:
        entity["version"] = entity.get("version", 1) + 1
