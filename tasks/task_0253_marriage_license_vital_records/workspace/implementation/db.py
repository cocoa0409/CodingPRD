"""In-memory data store and logical clock.

The store starts EMPTY on every boot. No seeding.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.applicants = {}
        self.officiants = {}
        self.applications = {}
        self.licenses = {}
        self.returns = {}
        self.records = {}
        self.certified_copies = {}
        self.amendments = {}
        self.apostilles = {}
        self.fee_waivers = {}
        self.ledger = {}
        # Monotonic insertion sequence to give a stable creation order even when
        # multiple rows share an identical created_at timestamp.
        self._seq = 0
        # Logical clock override; None means "use wall clock".
        self._clock = None

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    # ---- logical clock ----
    def now(self):
        if self._clock is not None:
            return self._clock
        return datetime.now(timezone.utc)

    def set_clock(self, dt):
        self._clock = dt

    def advance_clock(self, dt):
        self._clock = dt


store = Store()
