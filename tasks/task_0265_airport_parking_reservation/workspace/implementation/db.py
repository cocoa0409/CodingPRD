"""In-memory data store (PRD §2.4). Empty on every fresh boot — no seeding."""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso_ms():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.customers = {}
        self.vehicles = {}
        self.lots = {}
        self.rate_plans = {}
        self.cancellation_policies = {}
        self.reservations = {}
        self.stall_holds = {}
        self.shuttle_trips = {}
        self.payment_txns = {}
        # Monotonic sequence to provide a stable creation order for sorting,
        # independent of timestamp collisions.
        self._seq = 0
        # Server clock for time-dependent logic. None => use real wall clock.
        self.clock = None

    def next_seq(self):
        self._seq += 1
        return self._seq

    def current_utc(self):
        if self.clock is not None:
            return self.clock
        return datetime.now(timezone.utc)


store = Store()
