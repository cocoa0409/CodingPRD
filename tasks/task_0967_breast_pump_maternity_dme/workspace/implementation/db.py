import uuid
from datetime import datetime, timezone


class Store:
    """In-memory store. A fresh process starts completely empty; the logical
    clock starts at exactly 2026-05-01T00:00:00Z per PRD section 2.5."""

    def __init__(self):
        self.members = {}
        self.policies = {}
        self.prescriptions = {}
        self.catalog_items = {}
        self.pump_orders = {}
        self.order_lines = {}
        self.prior_auths = {}
        self.shipments = {}
        self.claims = {}
        self.schedules = {}
        self.resupply_orders = {}
        self.warranty_claims = {}
        self.seq = 0
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    """Entity timestamps follow the logical clock, never wall-clock time."""
    return fmt_dt(store.clock)


def today():
    return store.clock.astimezone(timezone.utc).date()
