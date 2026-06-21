"""In-memory data store. All state is process-local and starts empty on every boot.

No seeding, no preload, no disk persistence — re-running start.sh wipes everything.
"""
import threading
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        # one dict per entity collection, keyed by id
        self.roommate_profiles = {}
        self.room_listings = {}
        self.match_requests = {}
        self.households = {}
        self.memberships = {}
        self.bills = {}
        self.bill_splits = {}
        self.expenses = {}
        self.expense_shares = {}
        self.settlements = {}
        self.payment_reminders = {}
        self.disputes = {}
        # monotonic sequence so created_at ties never reorder insertion order
        self._seq = 0
        # pinned clock instant; None means use real wall-clock UTC
        self._pinned_now = None

    # ---- clock -----------------------------------------------------------
    def now(self):
        if self._pinned_now is not None:
            return self._pinned_now
        return datetime.now(timezone.utc)

    def set_clock(self, dt):
        self._pinned_now = dt

    # ---- ids / sequence --------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()
