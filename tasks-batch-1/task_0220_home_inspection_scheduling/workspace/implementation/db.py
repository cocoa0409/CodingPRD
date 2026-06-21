"""In-memory data store.

Every entity collection is a plain dict keyed by the server-minted UUID id.
The store starts EMPTY on every process boot — nothing is seeded, preloaded,
or hardcoded. All entities are created by tests via the declared API surface.
"""
import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits and trailing Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.territories = {}
        self.fee_schedules = {}
        self.inspectors = {}
        self.clients = {}
        self.agents = {}
        self.properties = {}
        self.inspection_orders = {}
        self.addons = {}
        self.reports = {}
        self.defects = {}
        self.deliveries = {}


# Single process-global store instance. Created empty at import time; never seeded.
db = Store()
