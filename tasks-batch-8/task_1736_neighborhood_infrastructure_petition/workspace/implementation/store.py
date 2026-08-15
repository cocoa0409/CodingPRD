"""In-memory data store + logical clock. The store starts empty on every boot."""
import threading
import uuid
from datetime import datetime, timezone

_lock = threading.RLock()


def _init_clock():
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clock = _init_clock()
        self.districts = {}
        self.owners = {}
        self.parcels = {}
        self.petitions = {}
        self.signatures = {}
        self.estimates = {}
        self.hearings = {}
        self.objections = {}
        self.resolutions = {}
        self.assessments = {}
        self.phases = {}
        self.change_orders = {}
        self.invoices = {}
        self.payments = {}
        # per-assessment principal history: [(when, balance_after_event, seq)]
        self.principal_history = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def put(self, collection, rec):
        """Insert a record, tagging it with a monotonic insertion sequence used
        as the deterministic tie-break for equal created_at timestamps."""
        rec["_seq"] = self.next_seq()
        self.__dict__[collection][rec["id"]] = rec


STORE = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return STORE.clock


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def touch(rec):
    """Refresh updated_at + bump version on a mutable resource."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 0) + 1
