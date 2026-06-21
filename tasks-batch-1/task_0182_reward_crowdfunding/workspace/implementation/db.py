"""In-memory data store. Starts EMPTY on every boot — no seeding ever."""
import uuid
from datetime import datetime, timezone


def now_iso():
    """Current wall clock as ISO 8601 UTC with 3 fractional digits (for created_at/updated_at)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.creators = {}
        self.backers = {}
        self.campaigns = {}
        self.tiers = {}
        self.stretch_goals = {}
        self.addons = {}
        self.pledges = {}
        self.pledge_addons = {}
        self.authorizations = {}
        self.refunds = {}
        self.surveys = {}
        # Monotonic insertion counter to give every record a stable, strictly
        # increasing sequence for deterministic ordering / created_at tie-breaks
        # when several records share the same millisecond timestamp.
        self._seq = 0
        # Logical server clock (ISO string). Defaults to real "now" until set.
        self.clock = now_iso()

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
