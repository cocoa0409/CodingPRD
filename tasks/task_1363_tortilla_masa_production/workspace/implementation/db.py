"""In-memory store + logical clock. No disk persistence of any kind."""
import uuid
from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.ingredient_lots = {}
        self.nixtamal_batches = {}
        self.products = {}
        self.lines = {}
        self.runs = {}
        self.allocations = {}
        self.changeovers = {}
        self.pack_orders = {}
        self.customers = {}
        self.windows = {}
        self.allotments = {}
        self.routes = {}
        self.stops = {}
        self.seq = 0                       # global insertion counter
        self.clock = CLOCK_DEFAULT         # logical clock (never wall-clock)
        self.touched = set()               # request-scoped version-bump dedup


store = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return store.clock


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_ts():
    return fmt_dt(datetime.now(timezone.utc))


def mint():
    """Fresh common-field skeleton for a new entity."""
    store.seq += 1
    ts = fmt_dt(store.clock)
    e = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": store.seq,
    }
    store.touched.add(e["id"])  # creation is this request's mutation
    return e


def touch(e):
    """Bump version + refresh updated_at; at most once per entity per request."""
    if e["id"] in store.touched:
        return
    store.touched.add(e["id"])
    e["version"] += 1
    e["updated_at"] = fmt_dt(store.clock)
