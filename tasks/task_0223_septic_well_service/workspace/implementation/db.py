"""In-memory data store.

Every collection is a plain dict keyed by id. The store starts EMPTY on every
boot — nothing is seeded. Tests build all preconditions via the API surface.
"""
import uuid
import itertools

from timeutil import iso_ms
from clock import clock


class Store:
    def __init__(self):
        self.accounts = {}
        self.technicians = {}
        self.sites = {}
        self.assets = {}
        self.service_plans = {}
        self.work_orders = {}
        self.routes = {}
        self.inspection_reports = {}
        self.permit_filings = {}
        self.repair_lines = {}
        self.reminders = {}
        # monotonically increasing creation sequence — a stable tie-break for
        # created_at ordering that does not depend on millisecond timestamp
        # collisions.
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def common_create():
    """System fields minted on creation of a common-fields entity."""
    ts = iso_ms()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(entity):
    """Mutation bump: refresh updated_at and increment version."""
    entity["updated_at"] = iso_ms()
    entity["version"] = entity.get("version", 0) + 1
