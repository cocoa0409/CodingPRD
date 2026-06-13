"""In-memory data store. Wiped on every fresh process boot (no persistence)."""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    """Holds one dict per entity collection, keyed by id."""

    def __init__(self):
        self.lock = threading.RLock()
        self.boutiques = {}
        self.customers = {}
        self.styles = {}
        self.sku_variants = {}
        self.fitting_rooms = {}
        self.fitting_room_holds = {}
        self.stylists = {}
        self.styling_appointments = {}
        self.markdown_schedules = {}
        self.sales_orders = {}
        self.order_lines = {}
        self.return_requests = {}
        self.special_orders = {}
        self.lookbooks = {}


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# Monotonic creation counter — guarantees a stable ascending sort order even
# when two resources are created within the same millisecond.
_seq_lock = threading.Lock()
_seq = 0


def _next_seq():
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def stamp_new(record):
    """Attach common system fields on create (PRD §2.4)."""
    ts = now_iso()
    record["id"] = record.get("id") or new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = _next_seq()
    return record


def touch(record):
    """Bump updated_at + version on every mutation (PRD §2.4 / §2.8)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
