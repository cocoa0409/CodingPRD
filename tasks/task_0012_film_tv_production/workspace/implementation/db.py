"""In-memory data store with thread safety."""
import uuid
from threading import RLock
from clock import clock


class Store:
    """A keyed table of records with system-managed common fields."""

    def __init__(self):
        # Each "table" is a dict: id -> record (dict)
        self.productions = {}
        self.scenes = {}
        self.roles = {}
        self.actors = {}
        self.auditions = {}
        self.locations = {}
        self.location_reservations = {}
        self.budget_categories = {}
        self.change_orders = {}
        self.equipment = {}
        self.equipment_events = {}
        self.crew_assignments = {}
        self.vendor_invoices = {}
        self.audit_logs = {}
        # Global lock that serializes mutations across the entire store.
        self.lock = RLock()


store = Store()


def new_id() -> str:
    return str(uuid.uuid4())


def init_common(record: dict):
    """Initialise common fields (id, created_at, updated_at, version)."""
    now = clock.now_iso()
    if "id" not in record:
        record["id"] = new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    return record


def init_append_only(record: dict):
    """Initialise append-only fields (id, created_at)."""
    now = clock.now_iso()
    if "id" not in record:
        record["id"] = new_id()
    record["created_at"] = now
    return record


def touch(record: dict):
    """Bump version and updated_at on a mutating change."""
    record["updated_at"] = clock.now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
