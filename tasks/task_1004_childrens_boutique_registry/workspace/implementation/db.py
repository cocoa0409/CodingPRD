"""In-memory data store, logical clock, id/timestamp helpers.

Storage is process-local and starts EMPTY on every boot. No seeding.
"""
import uuid
import random
import string
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": _DEFAULT_CLOCK}


def set_clock(dt):
    _clock["now"] = dt


def now():
    return _clock["now"]


def parse_iso(s):
    """Parse an ISO-8601 string into an aware UTC datetime. Returns None on failure."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % millis


def now_iso():
    return iso(now())


# ---------------------------------------------------------------------------
# Identifiers / sequence
# ---------------------------------------------------------------------------
_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ---------------------------------------------------------------------------
# Tables (all empty at boot)
# ---------------------------------------------------------------------------
stores = {}
customers = {}
skus = {}
registries = {}
registry_items = {}
registry_gifts = {}
orders = {}
consignment_shelves = {}
consignment_items = {}
trade_ins = {}
special_orders = {}


def new_entity(**fields):
    e = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(fields)
    return e


def touch(entity):
    """Register a mutation: bump version and refresh updated_at."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}
