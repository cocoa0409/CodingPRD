"""In-memory data store. Every byte is wiped on each fresh process boot —
no seeding, no preload, no persistence. Each collection is a dict keyed by id."""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.chefs = {}
        self.menus = {}
        self.travel_zones = {}
        self.availability_blocks = {}
        self.clients = {}
        self.bookings = {}
        self.grocery_runs = {}
        self.payments = {}
        self.recurring_plans = {}
        self.reschedule_requests = {}
        # Test clock: None means use real wall clock (PRD §3.11)
        self._fixed_now = None

    # ---- identity / timestamps ----
    @staticmethod
    def new_id():
        # UUID with no type prefix (PRD §2.4)
        return str(uuid.uuid4())

    def now(self):
        """Current effective clock (test clock if pinned, else wall clock)."""
        if self._fixed_now is not None:
            return self._fixed_now
        return datetime.now(timezone.utc)

    def set_clock(self, dt):
        self._fixed_now = dt

    @staticmethod
    def iso_millis(dt=None):
        if dt is None:
            dt = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


DB = Store()
