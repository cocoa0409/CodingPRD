"""In-memory data store and the shop's logical clock.

Everything lives in module-level dictionaries keyed by id. A fresh process
(and therefore every start.sh re-invocation) starts with an empty store and
the clock at exactly 2026-05-01T00:00:00Z. Nothing is seeded here.
"""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.customers = {}
        self.equipment_items = {}
        self.reservations = {}
        self.reservation_items = {}
        self.tune_tickets = {}
        self.season_leases = {}
        self.demo_credits = {}
        self.purchase_orders = {}
        self.damage_assessments = {}
        self.pickup_windows = {}
        self.pickup_bookings = {}
        self.shop_day_capacity = {}
        # internal bookkeeping: purchase order id -> [demo credit ids applied]
        self.order_credits = {}
        # monotonically increasing creation sequence (tie-breaks created_at)
        self.seq = 0
        # logical clock: the only notion of "now"
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


def now():
    return db.clock


def iso(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(db.clock)


def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def is_date_str(s):
    if not isinstance(s, str):
        return False
    try:
        parse_date(s)
        return True
    except (ValueError, TypeError):
        return False


def parse_dt(s):
    s2 = s.strip()
    if s2.endswith("Z"):
        s2 = s2[:-1] + "+00:00"
    dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_time_str(s):
    if not isinstance(s, str):
        return False
    try:
        datetime.strptime(s, "%H:%M")
        return True
    except (ValueError, TypeError):
        return False


def new_entity(fields):
    """Create a resource dict with the four common system-managed fields."""
    ts = now_iso()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    ent.update(fields)
    return ent


def touch(ent):
    """Every mutation refreshes updated_at and bumps version by exactly 1."""
    ent["updated_at"] = now_iso()
    ent["version"] += 1


def pub(ent):
    """Public view: strip internal bookkeeping keys."""
    return {k: v for k, v in ent.items() if not k.startswith("_")}
