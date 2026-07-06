"""In-memory data store and logical clock. Starts empty on every boot."""
import uuid
from datetime import datetime, timezone

# Server startup default logical clock
_DEFAULT_CLOCK = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


class DB:
    def __init__(self):
        self.products = {}
        self.stores = {}
        self.inventory = {}
        self.allocations = {}
        self.customers = {}
        self.orders = {}
        self.order_lines = {}
        self.layaways = {}
        self.special_orders = {}
        self.recalls = {}
        self.events = {}
        self.registries = {}
        self.registry_items = {}
        self.returns = {}
        self._clock = _DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    @property
    def clock(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt


db = DB()


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_dt():
    return db.clock


def now_ts():
    return fmt_ts(db.clock)
