"""In-memory data store, logical clock, and id/timestamp helpers.

Storage is process-local dicts keyed by id. Every boot starts empty; the store
is never seeded. start.sh re-invocation (per-test-server isolation) wipes all
state because the process is restarted.
"""
import uuid
import random
import string
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.tour_products = {}
        self.coaches = {}
        self.drivers = {}
        self.guides = {}
        self.departures = {}
        self.hotel_blocks = {}
        self.bookings = {}
        self.passengers = {}
        self.payments = {}
        self.vouchers = {}
        # Logical service clock. Default before any set call (PRD §2.9).
        self.clock = "2026-07-01T00:00:00Z"


db = Store()


def new_id():
    # Server-minted UUID, no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def now_iso():
    # Real wall-clock record timestamp, ISO 8601 UTC with three fractional digits.
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def base_common(entity):
    """Attach system-managed common fields (id, created_at, updated_at, version)."""
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version by one on every mutation (PRD §2.4/§2.7)."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1
