"""In-memory data store. Wiped on every process start; nothing is seeded."""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.salons = {}
        self.licenses = {}
        self.brands = {}
        self.exclusives = {}
        self.products = {}
        self.consultants = {}
        self.route_plans = {}
        self.route_stops = {}
        self.orders = {}
        self.order_items = {}
        self.shipments = {}
        self.promotions = {}
        self.redemptions = {}
        self.credit_entries = {}
        self.diversion_cases = {}
        self.seq = 0
        # Logical clock: startup default exactly 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def now_iso():
    """Wall-clock timestamp for meta.api_request_timestamp (3 fractional digits)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def dt_to_iso(dt):
    """Canonical ISO 8601 UTC; millisecond precision when sub-second present."""
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_iso():
    return dt_to_iso(store.clock)


def parse_dt(s):
    if isinstance(s, datetime):
        return s
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp_created(obj):
    ts = clock_iso()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next_seq()
    return obj


def touch(obj):
    obj["updated_at"] = clock_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj


def sort_key(obj):
    return (obj.get("created_at") or "", obj.get("_seq", 0))
