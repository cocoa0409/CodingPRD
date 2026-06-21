"""In-memory data store. State is wiped on every fresh process boot.

No seeding, preloading, or hardcoded entities. Every collection starts empty.
"""
import uuid
from datetime import datetime, timezone


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    # req_ prefix + 20 alphanumeric chars
    import random
    import string
    chars = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(chars) for _ in range(20))


class Store:
    def __init__(self):
        # Each entity type keyed by id -> dict record
        self.shops = {}
        self.customers = {}
        self.projects = {}
        self.specs = {}
        self.materials = {}
        self.reservations = {}
        self.machines = {}
        self.build_jobs = {}
        self.finish_selections = {}
        self.draws = {}
        self.change_orders = {}
        self.installations = {}
        self.punch_items = {}
        # monotonically increasing sequence to provide a stable creation order
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


# Single global store instance, constructed fresh per process.
store = Store()
