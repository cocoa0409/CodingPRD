"""In-memory data store. Starts completely empty on every boot — no seeding."""
import os
import uuid
from datetime import datetime, timezone

STORES = [
    "categories",
    "skus",
    "lots",
    "members",
    "club_plans",
    "club_subscriptions",
    "tasting_events",
    "flight_items",
    "tasting_seats",
    "special_orders",
    "orders",
    "order_lines",
    "shipments",
    "shipping_state_rules",
    "attestations",
]

# Each store is a dict keyed by entity id, holding dict records.
db = {name: {} for name in STORES}

# Insertion counter to guarantee stable created_at ordering when many records
# are minted within the same logical-clock tick.
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Current logical time rendered as ISO-8601 UTC with 3 fractional digits."""
    import clock
    dt = clock.now()
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return "%s.%03dZ" % (base, dt.microsecond // 1000)


def new_entity(fields):
    """Attach uniform identity/audit shape to a fresh record."""
    ts = now_ts()
    ent = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    ent.update(fields)
    ent["_seq"] = next_seq()
    return ent


def touch(ent):
    """Bump updated_at and version by exactly one."""
    ent["updated_at"] = now_ts()
    ent["version"] = ent.get("version", 1) + 1


def reset_state():
    """Test hook for local smoke runs (not used by the harness)."""
    for name in STORES:
        db[name].clear()
    _seq[0] = 0
