"""In-memory data store. Resets on every process boot — no seeding."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.brokerages = {}
        self.agents = {}
        self.buyers = {}
        self.listings = {}
        self.lockboxes = {}
        self.showings = {}
        self.offers = {}
        self.counter_rounds = {}
        self.contingencies = {}
        self.commission_ledgers = {}
        # logical server clock; None means "use wall clock"
        self.clock = None
        # monotonic creation sequence for stable created_at tie-breaking
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current wall-clock instant as ISO 8601 UTC with millisecond precision."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def server_now():
    """The logical clock used for showing temporal gating (datetime, UTC-aware)."""
    if db.clock is not None:
        return db.clock
    return datetime.now(timezone.utc)
