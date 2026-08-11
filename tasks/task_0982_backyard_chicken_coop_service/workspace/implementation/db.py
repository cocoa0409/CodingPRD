"""In-memory data store. A fresh process starts with an empty store and the
logical clock pinned at 2026-05-01T00:00:00Z. Nothing is seeded at startup."""
import itertools
import threading
import uuid
from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.seq = itertools.count(1)  # global insertion sequence for stable sorts
        self.clock = CLOCK_DEFAULT
        self.households = {}
        self.plans = {}
        self.subscriptions = {}
        self.coops = {}
        self.visits = {}
        self.engagements = {}
        self.routes = {}
        self.stops = {}
        self.products = {}
        self.orders = {}
        self.invoices = {}
        self.lines = {}
        self.windows = {}


store = Store()


def now():
    """The server logical clock. Never falls back to wall-clock time."""
    return store.clock


def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    """Attach common system fields to a freshly created primary resource."""
    t = now()
    rec["created_at"] = t
    rec["updated_at"] = t
    rec["version"] = 1
    rec["_seq"] = next(store.seq)
    return rec


def stamp_new_config(rec):
    """Config/subordinate resources carry only id and created_at."""
    rec["created_at"] = now()
    rec["_seq"] = next(store.seq)
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{v.astimezone(timezone.utc).microsecond // 1000:03d}Z"
        elif isinstance(v, list):
            out[k] = [dict(li) for li in v]
        else:
            out[k] = v
    return out
