"""In-memory data store and logical clock.

The store starts empty on every boot -- no seeding. All temporal logic reads
the logical clock; the server never falls back to wall-clock time.
"""

import threading
import uuid
from datetime import datetime, timezone

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.facilities = {}
        self.customers = {}
        self.products = {}
        self.tracks = {}
        self.equipment = {}
        self.incidents = {}
        self.railcars = {}
        self.lots = {}
        self.spot_orders = {}
        self.switch_orders = {}
        self.transfer_orders = {}
        self.weight_tickets = {}
        self.charges = {}
        self.invoices = {}
        # Global facility posture mirror (single-facility scope per PRD 2.6).
        self.posture = "NORMAL"
        self.seq = 0
        self.clock = CLOCK_START


STORE = Store()
LOCK = threading.RLock()


def next_seq():
    STORE.seq += 1
    return STORE.seq


def new_id():
    return str(uuid.uuid4())


def now():
    return STORE.clock


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return iso(STORE.clock)


def new_entity(table, fields, common=True):
    """Create an entity. common=False -> id/created_at only (SafetyIncident,
    SwitchOrder carry no updated_at/version)."""
    e = dict(fields)
    e["id"] = new_id()
    e["_seq"] = next_seq()
    ts = now_iso()
    e["created_at"] = ts
    if common:
        e["updated_at"] = ts
        e["version"] = 1
    table[e["id"]] = e
    return e


def touch(e):
    """Every mutation advances updated_at and increments version by one."""
    e["version"] += 1
    e["updated_at"] = now_iso()


def public(e):
    """Serialize: strip internal underscore-prefixed bookkeeping fields."""
    return {k: v for k, v in e.items() if not k.startswith("_")}
