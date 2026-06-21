"""In-memory data store.

Storage is process-local dicts keyed by id. Nothing is seeded at startup;
every entity is created through the declared API surface. start.sh re-invocation
launches a fresh process and therefore wipes all state.
"""
import threading
import uuid
from datetime import datetime, timezone

from response import now_iso


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # Each entity collection keyed by id.
        self.pricing_plans = {}
        self.machines = {}
        self.members = {}
        self.shifts = {}
        self.vends = {}
        self.reloads = {}
        self.wdf_orders = {}
        self.refund_claims = {}
        self.lost_found = {}
        self.loyalty_ledger = {}
        # Insertion order counter to provide a stable created_at tie-break sort.
        self._seq = 0
        # Server-held logical capture clock (PRD §2.5). Defaults to real "now"
        # on boot; Manager sets it via POST /_clock/advance.
        self.capture_clock = datetime.now(timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_create(obj, common_fields=True):
    """Populate system-managed common fields on create (PRD §2.4)."""
    ts = now_iso()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["_seq"] = db.next_seq()
    if common_fields:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    """Refresh updated_at and bump version on mutation (PRD §2.4 / §2.7)."""
    obj["updated_at"] = now_iso()
    if "version" in obj:
        obj["version"] += 1
