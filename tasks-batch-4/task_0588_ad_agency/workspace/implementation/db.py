"""In-memory data store.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or hardcoded;
every entity is created through the public API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

# --- collections ------------------------------------------------------------
CLIENTS = {}
RATE_CARDS = {}
STAFF = {}
PLACEMENTS = {}
RETAINERS = {}
SOWS = {}
CAMPAIGNS = {}
DELIVERABLES = {}
TIME_ENTRIES = {}
VENDOR_COSTS = {}
MEDIA_PLANS = {}
INSERTION_ORDERS = {}
INVOICES = {}

# --- the logical clock (PRD 2.5) -------------------------------------------
INITIAL_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_CLOCK = {"now": INITIAL_CLOCK}

_SEQ = itertools.count(1)


def clock_now():
    return _CLOCK["now"]


def clock_set(dt):
    _CLOCK["now"] = dt


def next_seq():
    return next(_SEQ)


def new_id():
    return str(uuid.uuid4())


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_now():
    return fmt_iso(datetime.now(timezone.utc))


def base_entity():
    ts = iso_now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def public(obj):
    """Strip internal (underscore-prefixed) bookkeeping keys."""
    if obj is None:
        return None
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def ordered(collection):
    """Ascending created_at order (PRD 2.3), stable via the creation sequence."""
    return sorted(collection.values(), key=lambda o: (o["created_at"], o["_seq"]))
