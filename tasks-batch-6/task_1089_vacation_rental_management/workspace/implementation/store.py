"""In-memory data store, logical clock, and id/timestamp helpers.

Storage is process-local and starts empty on every boot. No seeding.
"""
import random
import string
import threading
from datetime import datetime, timezone

_lock = threading.Lock()

# One dict per entity type, keyed by id.
owners = {}
guests = {}
vendors = {}
properties = {}
permits = {}
channel_listings = {}
pricing_rules = {}
bookings = {}
turnover_tasks = {}
inspections = {}
work_orders = {}
owner_statements = {}
statement_lines = {}
reviews = {}

TABLES = {
    "Owner": owners,
    "Guest": guests,
    "Vendor": vendors,
    "Property": properties,
    "Permit": permits,
    "ChannelListing": channel_listings,
    "PricingRule": pricing_rules,
    "Booking": bookings,
    "TurnoverTask": turnover_tasks,
    "Inspection": inspections,
    "WorkOrder": work_orders,
    "OwnerStatement": owner_statements,
    "StatementLine": statement_lines,
    "Review": reviews,
}

# Logical clock: default 2026-05-01T00:00:00Z, never wall-clock fallback.
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": DEFAULT_CLOCK}

_seq = {"n": 0}


def now_clock():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_uuid():
    import uuid
    return str(uuid.uuid4())


def iso_now():
    """Wall-clock UTC timestamp with 3 fractional digits and Z suffix."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def new_common(with_common=True):
    """Return a base dict with id/created_at (+ updated_at/version if common)."""
    ts = iso_now()
    base = {"id": new_uuid(), "created_at": ts, "_seq": next_seq()}
    if with_common:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def touch(entity):
    """Bump updated_at + version on a mutation (skip immutable StatementLine)."""
    if "version" in entity:
        entity["updated_at"] = iso_now()
        entity["version"] = entity["version"] + 1
