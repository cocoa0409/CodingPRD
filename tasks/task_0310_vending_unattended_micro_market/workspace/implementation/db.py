"""In-memory data store. Starts empty on every boot — NO seeding."""
import itertools
import uuid
from datetime import datetime, timezone

from response import now_iso


class Store:
    def __init__(self):
        # one dict per entity, keyed by id
        self.host_sites = {}
        self.products = {}
        self.machines = {}
        self.slots = {}
        self.lots = {}
        self.drivers = {}
        self.routes = {}
        self.stops = {}
        self.visits = {}
        self.sales = {}
        self.statements = {}
        self.tickets = {}

        # monotonic counter to break created_at ties deterministically
        self._seq = itertools.count(1)

        # logical clock (PRD 2.11). Defaults to real UTC until set.
        self._clock = None

    # --- id / timestamp / sequence ---
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)

    # --- logical clock ---
    def clock(self):
        if self._clock is not None:
            return self._clock
        return datetime.now(timezone.utc)

    def set_clock(self, dt):
        self._clock = dt

    def clock_iso(self):
        dt = self.clock()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{dt.microsecond // 1000:03d}Z"


db = Store()


def stamp_create(obj, common_fields=True):
    """Attach id + system fields at creation time."""
    ts = now_iso()
    obj["id"] = db.new_id()
    obj["created_at"] = ts
    obj["_seq"] = db.next_seq()
    if common_fields:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    """Refresh updated_at and bump version on a mutation (PRD 2.4)."""
    if "version" in obj:
        obj["updated_at"] = now_iso()
        obj["version"] = obj["version"] + 1


def public(obj):
    """Strip internal fields (those prefixed with _) for output."""
    return {k: v for k, v in obj.items() if not k.startswith("_")}
