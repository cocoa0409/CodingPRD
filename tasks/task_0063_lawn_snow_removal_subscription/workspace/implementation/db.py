import uuid
import threading
from response import now_iso


class Store:
    """In-memory store. Starts empty on every boot. No seeding."""

    def __init__(self):
        self.lock = threading.RLock()
        self.customers = {}
        self.properties = {}
        self.preferences = {}
        self.contracts = {}
        self.routes = {}
        self.route_stops = {}
        self.crews = {}
        self.equipment = {}
        self.weather_readings = {}
        self.visits = {}
        self.skip_requests = {}
        self.invoices = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def new_common(extra=None):
    """Common-field resource scaffolding."""
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """Mutation bump: refresh updated_at and increment version."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
