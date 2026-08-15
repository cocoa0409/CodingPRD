"""In-memory data store and the server-held logical clock.

The store starts empty on every boot — no seeding of any kind. Every entity
any caller needs is constructed through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timezone


class Clock:
    """Logical clock. Startup default is exactly 2026-08-01T00:00:00Z.

    The clock never falls back to wall-clock time on its own; it moves only
    when a client drives it through POST /_clock/set_current_utc.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        with self._lock:
            return self._now

    def set(self, dt):
        with self._lock:
            self._now = dt
        return self._now


def parse_iso(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.clock = Clock()
        # global request lock: mutations and reads are serialized so a
        # multi-resource cascade can never interleave with another request
        self.lock = threading.RLock()
        # entity stores, keyed by id — all start empty
        self.sites = {}
        self.growers = {}
        self.contracts = {}
        self.barns = {}
        self.pig_groups = {}
        self.feed_orders = {}
        self.mortality_reports = {}
        self.packer_slots = {}
        self.truck_washes = {}
        self.market_loads = {}
        self.barn_washes = {}
        self.manure_plans = {}
        self.manure_applications = {}
        self.maintenance_tickets = {}
        self.settlements = {}
        # monotonic arrival counter used to break created_at ties
        # deterministically (several records can share one logical timestamp)
        self._seq_lock = threading.Lock()
        self._seq = 0

    def next_seq(self):
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def now(self):
        return self.clock.now()

    def now_str(self):
        return fmt_ts(self.clock.now())


store = Store()
