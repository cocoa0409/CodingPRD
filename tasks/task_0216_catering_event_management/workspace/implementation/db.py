"""In-memory data store. Wiped on every process boot — no persistence.

All entities are kept in plain dicts keyed by UUID string id. The logical
clock and the global staffing-pool total live here as well, because every
time-relative calculation reads the clock (PRD §3.12) and the pool is a single
global capacity (PRD §2.9).
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.clients = {}
        self.packages = {}
        self.venues = {}
        self.routes = {}
        self.orders = {}
        self.add_ons = {}
        self.delivery_legs = {}
        self.staffing_reservations = {}
        self.change_requests = {}
        self.ledger_entries = {}

        # Monotonic sequence used as a deterministic creation-order tie-break so
        # that two rows minted in the same millisecond still sort by insertion
        # order (created_at ASC, PRD §2.3 / §2.8). Independent of id.
        self._seq = 0

        # Logical clock. None means "use wall-clock"; tests set it explicitly
        # via POST /catering/_clock/set_current_utc (PRD §3.12).
        self.current_utc = None

        # Global staffing pool total capacity (PRD §2.9). Defaults to 0 until an
        # admin sets it; remaining = total - sum(reserved_staff of HELD rows).
        self.staff_pool_total = 0

    # -- id / sequence / time helpers --
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """The server clock used for stored timestamps (real wall time)."""
        return datetime.now(timezone.utc)

    def logical_now(self):
        """The clock that time-relative business rules read (PRD §3.12)."""
        if self.current_utc is not None:
            return self.current_utc
        return datetime.now(timezone.utc)

    # -- staffing pool --
    def held_staff(self):
        return sum(
            r["reserved_staff"]
            for r in self.staffing_reservations.values()
            if r["status"] == "HELD"
        )

    def staff_remaining(self):
        return self.staff_pool_total - self.held_staff()


db = Store()
