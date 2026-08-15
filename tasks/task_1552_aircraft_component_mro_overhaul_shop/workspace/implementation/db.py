"""In-memory data store and logical clock. Store starts empty on every boot."""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.customers = {}
        self.parts = {}
        self.directives = {}
        self.units = {}
        self.work_orders = {}
        self.discrepancies = {}
        self.compliances = {}
        self.requisitions = {}
        self.test_cells = {}
        self.bookings = {}
        self.certificates = {}
        self.exchanges = {}
        self.leases = {}
        self.claims = {}
        self.invoices = {}
        self.traces = {}
        self.seq = 0
        self.cert_seq = 0
        # Logical clock: starts exactly at 2026-08-01T00:00:00Z, never wall clock.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def next_seq():
    store.seq += 1
    return store.seq


def next_cert_number():
    store.cert_seq += 1
    return "8130-%06d" % store.cert_seq


def clock_now():
    return store.clock


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_dt(store.clock)


def current_date():
    return store.clock.date()


def parse_dt(s):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if isinstance(s, datetime):
        dt = s
    else:
        v = str(s).strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
