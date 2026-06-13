"""In-memory data store for the Stadium Venue Concessions API.

Storage is purely in-process Python dicts keyed by id. The store starts EMPTY
on every process boot — nothing is seeded, preloaded, or hardcoded. The test
harness builds all state via API calls, and re-invoking start.sh (a fresh
process) wipes everything.
"""

import threading
import uuid
from datetime import datetime, timezone


class Store:
    """Holds one dict per entity collection, keyed by id, plus a logical clock."""

    def __init__(self):
        self.lock = threading.RLock()
        # One dict per entity type. All empty at boot.
        self.venues = {}
        self.products = {}
        self.events = {}
        self.stands = {}
        self.menu_items = {}
        self.inventory_lots = {}
        self.replenishments = {}
        self.transfers = {}
        self.orders = {}
        self.order_lines = {}
        self.staff_shifts = {}
        self.waste_records = {}
        self.revenue_share_statements = {}
        self.patrons = {}

        # Monotonic insertion counter to break created_at ties for deterministic
        # ordering (created_at + seq gives a stable total order).
        self._seq = 0

        # Logical clock used for lot-expiry comparisons (PRD §3.5). Settable via
        # the test hook POST /_clock/set_current_utc. Defaults to wall-clock UTC.
        self._clock = None  # None => use real wall clock

    # ---- id / time helpers ----
    def new_id(self):
        return str(uuid.uuid4())

    def now(self):
        """Server timestamp for created_at/updated_at (always real wall clock,
        ISO 8601 UTC with three fractional digits)."""
        return _iso_millis(datetime.now(timezone.utc))

    def next_seq(self):
        self._seq += 1
        return self._seq

    # ---- logical clock for expiry ----
    def current_utc(self):
        """The server's logical UTC clock used for expiry checks."""
        if self._clock is not None:
            return self._clock
        return datetime.now(timezone.utc)

    def set_clock(self, dt):
        self._clock = dt


def _iso_millis(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits
    and a trailing Z (PRD §2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Single global store instance for the process. Recreated fresh each boot.
store = Store()
