"""In-memory data store. Wiped on every process boot — NO seeding."""
import uuid
from datetime import datetime, timezone


class Clock:
    """Server's notion of 'now', advanceable via /_clock/set_current_utc."""
    def __init__(self):
        self._override = None  # datetime (aware UTC) or None

    def set(self, dt):
        self._override = dt

    def now(self):
        if self._override is not None:
            return self._override
        return datetime.now(timezone.utc)

    def now_iso(self):
        dt = self.now().astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    def today_date(self):
        """Current date as YYYY-MM-DD string (UTC)."""
        return self.now().astimezone(timezone.utc).strftime("%Y-%m-%d")


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.markets = {}
        self.vendors = {}
        self.permits = {}
        self.applications = {}
        self.booths = {}
        self.market_days = {}
        self.booth_assignments = {}
        self.check_ins = {}
        self.sales_reports = {}
        self.voucher_batches = {}
        self.voucher_redemptions = {}
        self.clock = Clock()
        # Monotonic creation counter to provide a strict total order for
        # created_at-based sorting/ranking even when timestamps collide.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return db.clock.now_iso()
