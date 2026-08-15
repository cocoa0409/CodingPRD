"""In-memory data store. Everything resets on process restart."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.shops = {}
        self.customers = {}
        self.motors = {}
        self.work_orders = {}
        self.test_records = {}
        self.quotes = {}
        self.coil_data_records = {}
        self.pool_contracts = {}
        self.pool_loans = {}
        self.invoices = {}
        self.warranty_claims = {}
        # Logical clock: starts exactly at 2026-08-01T00:00:00Z
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self.clock

    def set_clock(self, dt):
        self.clock = dt


store = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return format_ts(store.now())


def format_ts(dt):
    if dt is None:
        return None
    # ISO 8601 UTC with three fractional digits, trailing Z
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = int(dt.microsecond / 1000)
    return f"{s}.{ms:03d}Z"


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
