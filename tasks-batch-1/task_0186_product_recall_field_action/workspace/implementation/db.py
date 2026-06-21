"""In-memory data store. Starts EMPTY on every process boot — no seeding, no preload."""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # One dict per entity collection, keyed by id.
        self.products = {}
        self.lots = {}
        self.units = {}
        self.customers = {}
        self.recalls = {}
        self.affected_lots = {}
        self.quarantine_holds = {}
        self.notifications = {}
        self.dispositions = {}
        self.regulatory_reports = {}
        self.effectiveness_checks = {}
        # Monotonic sequence to break ties when timestamps are identical, so
        # creation order (created_at asc) is stable.
        self._seq = 0
        # Pinned test clock; None means use real wall clock.
        self._pinned_now = None

    def next_seq(self):
        self._seq += 1
        return self._seq

    # --- clock --------------------------------------------------------------
    def set_clock(self, dt):
        self._pinned_now = dt

    def now(self):
        if self._pinned_now is not None:
            return self._pinned_now
        return datetime.now(timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def iso_now():
    """ISO 8601 UTC, three fractional digits, Z suffix — for created_at/updated_at."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
