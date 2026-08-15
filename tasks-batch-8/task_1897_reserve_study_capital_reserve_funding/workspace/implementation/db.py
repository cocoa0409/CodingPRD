"""In-memory data store. All state lives here and starts empty on every boot."""

import uuid
import threading
from datetime import datetime, timezone, timedelta


class Store:
    def __init__(self):
        self.lock = threading.Lock()
        # Entity collections keyed by id
        self.state_reserve_rules = {}       # id -> dict
        self.associations = {}              # id -> dict
        self.reserve_studies = {}           # id -> dict
        self.components = {}                # id -> dict
        self.funding_plans = {}             # id -> dict
        self.site_visits = {}               # id -> dict
        self.expenditures = {}              # id -> dict
        self.disclosures = {}               # id -> dict
        # Logical clock — default 2026-08-01T00:00:00Z
        self._logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    # --- Logical clock ---
    def get_clock(self):
        return self._logical_clock

    def set_clock(self, dt):
        self._logical_clock = dt

    def now_iso(self):
        """Current logical clock as ISO 8601 UTC with 3 fractional digits."""
        dt = self._logical_clock
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    def now_date(self):
        """Current logical clock date as YYYY-MM-DD."""
        return self._logical_clock.strftime("%Y-%m-%d")

    @staticmethod
    def new_id():
        return str(uuid.uuid4())

    def make_common_fields(self):
        """Return the four system-managed common fields for a new resource."""
        now = self.now_iso()
        return {
            "id": self.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }

    def touch(self, entity):
        """Bump version and updated_at on a mutation."""
        entity["version"] += 1
        entity["updated_at"] = self.now_iso()


# Global singleton store
store = Store()
