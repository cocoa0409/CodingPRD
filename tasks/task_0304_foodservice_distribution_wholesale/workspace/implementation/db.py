"""In-memory data store for the foodservice distribution API.

All state lives in module-level dicts keyed by id. There is NO persistence:
the process is restarted before every test, which wipes everything. No seeding
of entities is ever performed at startup — every entity is created by tests via
the declared API surface.
"""
import threading
import uuid
from datetime import datetime, timezone


# Each entity collection is a dict {id: record}. One dict per entity type.
distributors = {}
warehouses = {}
routes = {}
products = {}
price_tiers = {}
customers = {}
order_guides = {}
order_guide_items = {}
inventory_lots = {}
orders = {}
order_lines = {}
shipments = {}
returns = {}

# A single global lock to keep multi-resource mutations atomic & consistent.
lock = threading.RLock()


def reset():
    """Clear all collections. Used only for safety; boot starts empty anyway."""
    for coll in (
        distributors, warehouses, routes, products, price_tiers, customers,
        order_guides, order_guide_items, inventory_lots, orders, order_lines,
        shipments, returns,
    ):
        coll.clear()


def new_id():
    """Generate a UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso():
    """Current wall-clock instant as ISO 8601 UTC with three fractional digits.

    Used for created_at / updated_at / api_request_timestamp. This is the
    *real* server time, distinct from a distributor's logical current_utc
    (the test-driven clock used for cutoff/delivery/freshness math).
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
