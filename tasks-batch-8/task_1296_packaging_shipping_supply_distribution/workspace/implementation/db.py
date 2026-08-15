"""In-memory data store + logical clock. Starts completely empty on every boot —
no seeding; tests construct all state via the declared API surface."""
import itertools
import uuid
from datetime import datetime, timezone

# Entity tables: id -> dict
accounts = {}
products = {}
warehouses = {}
inventory = {}            # inventory rows by id
inventory_by_pair = {}    # (product_id, warehouse_id) -> id
quantity_breaks = {}
orders = {}
order_lines = {}
custom_print_jobs = {}
returns = {}
return_lines = {}
restock_notifications = {}

# Monotonic insertion sequence (stable tie-break for equal created_at)
_seq = itertools.count(1)

# Logical clock: startup default per PRD §2.5; never falls back to wall clock.
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def touch(entity):
    """Refresh updated_at and bump version (common-fields entities)."""
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 1) + 1
