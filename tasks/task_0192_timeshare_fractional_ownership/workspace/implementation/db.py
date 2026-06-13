"""In-memory data store. Starts empty on every boot — NO seeding."""
import itertools
import threading
import uuid

from response import now_iso


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # One dict per entity type, keyed by id.
        self.resorts = {}
        self.owners = {}
        self.inventory_units = {}
        self.contracts = {}
        self.points_accounts = {}
        self.reservations = {}
        self.invoices = {}
        self.payments = {}
        self.special_assessments = {}
        self.exchange_deposits = {}
        self.resale_transfers = {}
        self.delinquency_cases = {}
        # Monotonic creation sequence for stable created_at ASC ordering even
        # when timestamps collide (resort clock is frozen between /_clock calls).
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_create(obj):
    """Set system common fields on create: id, created_at, updated_at, version, _seq."""
    ts = now_iso()
    obj.setdefault("id", new_id())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = db.next_seq()
    return obj


def touch(obj):
    """Mutation bump: refresh updated_at and increment version by one."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj
