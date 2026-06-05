"""In-memory data store.

Storage is plain Python dicts keyed by id. The store starts EMPTY on every boot
— no seeding, no preloaded entities. Tests construct all preconditions through
the declared API surface.
"""
import threading
import uuid
from datetime import datetime, timezone


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # one dict per entity collection, keyed by id
        self.productions = {}
        self.budget_lines = {}
        self.shooting_days = {}
        self.scenes = {}
        self.crew_members = {}
        self.assignments = {}
        self.call_sheets = {}
        self.locations = {}
        self.location_permits = {}
        self.residual_events = {}
        self.union_fringes = {}
        self.dailies = {}
        # monotonic creation sequence to break created_at ties deterministically
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


# single global store; recreated fresh on every process start
db = Store()
