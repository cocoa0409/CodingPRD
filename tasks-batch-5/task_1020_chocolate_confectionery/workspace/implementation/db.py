"""In-memory data store, logical clock, and shared utilities.

Storage is in-memory only (Python dicts) and starts EMPTY on every boot.
No entity is seeded / preloaded / hardcoded at startup.
"""
import itertools
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

# Logical-clock startup default (PRD §4 / endpoint table): 2026-07-01T00:00:00Z
CLOCK_DEFAULT = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.customers = {}
        self.products = {}
        self.bundle_components = {}
        self.molds = {}
        self.tempering_lines = {}
        self.batches = {}
        self.orders = {}
        self.order_lines = {}
        self.reservations = {}
        self.custom_orders = {}
        self.mold_bookings = {}
        self.subscriptions = {}
        self.subscription_shipments = {}
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def now_real():
    """Wall-clock UTC used for created_at / updated_at (record creation time)."""
    return datetime.now(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse an ISO 8601 instant. Raises ValueError on bad input."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


# --------------------------------------------------------------------------
# Numeric helpers (PRD §2.6 — integer cents, round half up)
# --------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal to whole cents, half away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def D(x):
    return Decimal(str(x))


# --------------------------------------------------------------------------
# Common fields + mutation bookkeeping (PRD §2.4 / §2.9)
# --------------------------------------------------------------------------
def make_common():
    now = now_real()
    return {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def make_common_immutable():
    """BundleComponent — only id + created_at (PRD §2.4)."""
    return {
        "id": db.new_id(),
        "created_at": now_real(),
        "_seq": db.next_seq(),
    }


def touch(entity):
    """Register a mutation: bump version + refresh updated_at."""
    if "version" in entity:
        entity["version"] += 1
        entity["updated_at"] = now_real()


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
