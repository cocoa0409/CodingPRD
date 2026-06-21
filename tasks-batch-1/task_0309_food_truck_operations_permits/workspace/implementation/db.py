"""In-memory data store (PRD §2: in-memory only, empty on every boot).

NO seeding, preloading, or hardcoded entities. Every collection starts empty;
tests construct all entity data via the declared API surface. State is wiped
implicitly because the process is re-launched on every per-test reboot.
"""

import datetime

from clock import new_id, now_iso


# A default logical-clock epoch. The clock is purely logical and only advanced
# by POST /_clock/set_current_utc; this default is an in-memory starting point,
# not seeded entity data.
DEFAULT_CLOCK = datetime.datetime(2025, 1, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.commissaries = {}
        self.trucks = {}
        self.permits = {}
        self.spots = {}
        self.events = {}
        self.bookings = {}
        self.menu_items = {}
        self.prep_batches = {}
        self.staff_shifts = {}
        self.utility_logs = {}
        self.orders = {}
        self.order_lines = {}

        # Monotonic insertion counter for stable created_at ordering / tie-breaks.
        self._seq = 0

        # Logical clock (UTC). Advanced only by the clock endpoint.
        self.clock = DEFAULT_CLOCK

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_record(self, fields, common_fields=True):
        """Create a record dict with system-managed common fields (§2.4).

        common_fields=True -> id, created_at, updated_at, version (full record).
        common_fields=False -> id, created_at only (append-only UtilityLog).
        """
        rec = dict(fields)
        rec["id"] = new_id()
        ts = now_iso()
        rec["created_at"] = ts
        rec["_seq"] = self.next_seq()
        if common_fields:
            rec["updated_at"] = ts
            rec["version"] = 1
        return rec

    def touch(self, rec):
        """Mark a full record as mutated: bump version, refresh updated_at (§2.4)."""
        if "version" in rec:
            rec["version"] += 1
            rec["updated_at"] = now_iso()


# Singleton store for the process. Recreated fresh on each boot (empty).
db = Store()
