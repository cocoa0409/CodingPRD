"""In-memory data store. Fresh on every process boot — no seeding, no disk."""

import uuid
import threading
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # one dict per entity collection, keyed by id
        self.customers = {}
        self.units = {}
        self.floor_plan_loans = {}
        self.curtailments = {}
        self.deals = {}
        self.trade_ins = {}
        self.technicians = {}
        self.repair_orders = {}
        self.service_lines = {}
        self.parts = {}
        self.part_lines = {}
        self.storage_bays = {}
        self.storage_agreements = {}
        self.test_ride_waivers = {}
        self.warranty_claims = {}
        # monotonically increasing sequence to order creates that share a timestamp
        self._seq = 0
        # logical clock (test-driving); defaults to wall clock at boot
        self.clock = datetime.now(timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current server time as ISO 8601 UTC (3 fractional digits).

    Reads the logical test-driving clock so created_at/updated_at advance with
    the clock the tests set (PRD 2.10). The declining-interest segment walk and
    other temporal logic depend on record timestamps tracking that clock.
    """
    return iso(db.clock)


def wall_now_iso():
    """Wall-clock ISO timestamp for response-envelope metadata (request time)."""
    return iso(datetime.now(timezone.utc))


def iso(dt):
    """Format a datetime as ISO 8601 UTC with millisecond precision and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime, or None on failure."""
    if value is None or not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
