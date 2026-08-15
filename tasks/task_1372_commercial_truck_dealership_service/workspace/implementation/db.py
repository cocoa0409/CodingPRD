"""In-memory store + logical clock. Store starts EMPTY on every boot — no seeding."""
import uuid
from datetime import datetime, timezone

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.clock = CLOCK_START
        self.seq = 0  # global insertion sequence; proxies created_at ordering
        self.customer_accounts = {}
        self.factory_build_slots = {}
        self.factory_orders = {}
        self.units = {}
        self.floor_plan_entries = {}
        self.trade_appraisals = {}
        self.service_bays = {}
        self.mobile_service_units = {}
        self.repair_orders = {}
        self.repair_order_lines = {}
        self.service_bookings = {}
        self.warranty_claims = {}
        self.parts = {}
        self.parts_sales = {}
        self.parts_sale_lines = {}

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex


def _fmt_ms(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (common fields, meta)."""
    if dt is None:
        return None
    return _fmt_ms(dt)


def fmt_dt(dt):
    """ISO 8601 UTC; seconds when no fractional part, else three fractional digits."""
    if dt is None:
        return None
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return _fmt_ms(dt)


def fmt_date(d):
    if d is None:
        return None
    return d.isoformat()


def now_dt():
    return store.clock


def now_iso():
    return fmt_ts(store.clock)


def clock_date():
    return store.clock.date()


def stamp_new(entity):
    """Assign id, created_at, updated_at, version=1, insertion seq."""
    entity["id"] = new_id()
    entity["_seq"] = store.next_seq()
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def stamp_new_ledger(entity):
    """FloorPlanEntry: id + created_at only (no updated_at / version)."""
    entity["id"] = new_id()
    entity["_seq"] = store.next_seq()
    entity["created_at"] = now_iso()
    return entity


def touch(entity):
    """Every mutation refreshes updated_at and increments version."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
