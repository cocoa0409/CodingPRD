"""In-memory data store + logical clock. Starts empty on every boot."""
import threading
import uuid
from datetime import datetime, timezone


def _epoch_start():
    return datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = 0  # monotonic insertion counter (stable sort tiebreak)
        self.clock = _epoch_start()
        self.zones = {}
        self.residents = {}
        self.kits = {}
        self.pickups = {}
        self.partners = {}
        self.assignments = {}
        self.dropboxes = {}
        self.readings = {}
        self.tickets = {}
        self.credits = {}
        self.funds = {}
        self.charities = {}
        self.reports = {}
        self.periods = {}


store = Store()


def now_dt():
    """Current logical clock as an aware UTC datetime."""
    return store.clock


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(store.clock)


def new_id():
    return str(uuid.uuid4())


def new_record():
    """Base fields for common-field entities: id/created_at/updated_at/version."""
    t = now_iso()
    store.seq += 1
    return {
        "id": new_id(),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": store.seq,
    }


def touch(rec):
    """Mutation bookkeeping: refresh updated_at and bump version."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1


def next_seq():
    store.seq += 1
    return store.seq
