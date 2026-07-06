import itertools
import uuid
from datetime import timezone

from clock import LogicalClock, format_iso_ms


class DB:
    """In-memory data store. Starts EMPTY on every boot. No seeding."""

    def __init__(self):
        self.clock = LogicalClock()
        # entity_type -> { id -> record dict }
        self.programs = {}
        self.cameras = {}
        self.calibrations = {}
        self.owners = {}
        self.citations = {}
        self.contests = {}
        self.hearings = {}
        self.payments = {}
        self.vendor_contracts = {}
        self.notices = {}
        # monotonic creation sequence for stable created_at ordering
        self._seq = itertools.count(1)
        # wall-clock creation instant is only used to build the *string* created_at;
        # ordering is done by _seq so ties never reorder.

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)


# Singleton store, reset by app on boot
db = DB()
