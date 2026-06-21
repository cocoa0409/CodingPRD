"""In-memory data store.

Every entity lives in a plain dict keyed by its server-minted UUID. The store is
created fresh on every process boot — there is NO persistence and NO seeding. The
test harness re-launches the server via start.sh before each test, so a fresh
module import wipes all state.

A monotonically increasing sequence is attached to each created record (``_seq``)
so list endpoints can sort by creation order deterministically even when several
records share the same millisecond timestamp.
"""

import itertools
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        self.venues = {}
        self.rooms = {}
        self.packages = {}
        self.staff_members = {}
        self.bookings = {}
        self.add_ons = {}
        self.guest_parties = {}
        self.waivers = {}
        self.staff_assignments = {}
        self.payments = {}
        # SystemClock singleton; current_utc starts at server-boot wall time.
        self.clock = None
        self._seq_counter = itertools.count(1)
        self._init_clock()

    def _init_clock(self):
        self.clock = {
            "id": new_id(),
            "created_at": now_iso(),
            "current_utc": now_iso(),
        }

    def next_seq(self):
        return next(self._seq_counter)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits and trailing Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# Single global store instance, created at import time (fresh per process).
db = DB()
