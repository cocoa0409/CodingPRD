"""In-memory data store. Every byte of state lives here and is wiped on each
fresh process boot — no seeding, no persistence, no disk."""
import threading
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        # entity collections keyed by id
        self.customers = {}
        self.pools = {}
        self.service_plans = {}
        self.routes = {}
        self.visits = {}
        self.readings = {}
        self.work_orders = {}
        self.seasonal_events = {}
        self.invoices = {}
        # monotonic sequence to order rows that share a created_at millisecond
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


def now_iso_ms(dt=None):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
