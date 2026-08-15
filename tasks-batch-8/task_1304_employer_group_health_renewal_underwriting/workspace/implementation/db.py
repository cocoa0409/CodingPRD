"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return uuid.uuid4().hex


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (wall clock)."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


class Store:
    """All state lives here. Instantiated once per process; a fresh process
    therefore starts with zero entities."""

    def __init__(self):
        self.brokers = {}
        self.cases = {}
        self.censuses = {}
        self.claims = {}
        self.plans = {}
        self.quotes = {}
        self.stop_losses = {}
        self.rounds = {}
        self.enrollment_events = {}
        self.disclosures = {}
        self.seq = 0  # monotonic insertion counter for stable created_at ordering
        # Logical clock default: exactly 2026-08-01T00:00:00Z at startup (PRD 2.8)
        self.logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def tick(self):
        self.seq += 1
        return self.seq


store = Store()


def new_record():
    """Common system-managed fields for every resource (PRD 2.4)."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.tick(),
    }


def touch(rec):
    """Refresh updated_at and increment version on any mutation (PRD 2.4)."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1
