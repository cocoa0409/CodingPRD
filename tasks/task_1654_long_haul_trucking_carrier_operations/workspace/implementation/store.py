"""In-memory data store. Starts empty on every boot except the logical clock
default (2026-08-01T00:00:00Z), which is PRD-declared system-initial state."""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.drivers = {}
        self.tractors = {}
        self.customers = {}
        self.lanes = {}
        self.fuel_rates = {}
        self.loads = {}
        self.trips = {}
        self.duty_events = {}
        self.check_calls = {}
        self.accessorials = {}
        self.fuel_purchases = {}
        self.safety_events = {}
        self.settlements = {}
        self.invoices = {}
        # Logical clock: PRD-mandated startup default; never wall-clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0
        self.lock = threading.RLock()


store = Store()


def now():
    return store.clock


def next_seq():
    store.seq += 1
    return store.seq


def new_id():
    return str(uuid.uuid4())


def init_common(e):
    """Common fields for primary resources (PRD section 2.5)."""
    e["id"] = new_id()
    e["created_at"] = now()
    e["updated_at"] = now()
    e["version"] = 1
    e["_seq"] = next_seq()
    return e


def init_telemetry(e):
    """DutyEvent / CheckCall: id + created_at only (PRD section 2.5)."""
    e["id"] = new_id()
    e["created_at"] = now()
    e["_seq"] = next_seq()
    return e


def touch(e):
    """Cascading mutation bookkeeping (PRD section 2.7)."""
    e["updated_at"] = now()
    e["version"] += 1
