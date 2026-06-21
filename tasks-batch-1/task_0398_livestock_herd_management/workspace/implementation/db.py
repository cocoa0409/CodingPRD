"""In-memory data store.

All state is held in plain dicts keyed by id. The store starts EMPTY on every
process boot — nothing is seeded or preloaded. Every entity is created by the
test suite through the declared API surface. start.sh re-launches a fresh
process before every test, which wipes all of this.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # one dict per collection, keyed by id
        self.herds = {}
        self.pastures = {}
        self.drug_products = {}
        self.feed_rations = {}
        self.animals = {}
        self.weight_records = {}
        self.breeding_records = {}
        self.health_treatments = {}
        self.movement_records = {}
        self.sale_lots = {}
        self.weight_tickets = {}
        self.mortality_records = {}
        self.trace_events = {}
        # monotonic counter to provide a stable creation order tie-break that
        # does not depend on timestamp resolution
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with exactly three fractional digits, e.g.
    2025-05-24T10:30:00.123Z. This is a *server* (wall-clock) timestamp for
    created_at / updated_at / meta — NOT the logical clock."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"
