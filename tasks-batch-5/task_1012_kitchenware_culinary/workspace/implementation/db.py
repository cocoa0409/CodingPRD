"""In-memory data store and logical clock.

The store starts EMPTY on every boot. Nothing is seeded — every entity is
created by tests through the declared API surface.
"""
from constants import DEFAULT_CLOCK
from util import new_id, format_dt, parse_dt

# One dict per entity type, keyed by id.
stores = {}
skus = {}
members = {}
orders = {}
cooking_classes = {}
class_registrations = {}
service_tickets = {}
returns = {}
special_orders = {}
registries = {}

# Monotonic creation sequence (tie-breaker for created_at sort).
_seq = 0

# Server logical clock (aware UTC datetime).
_clock = parse_dt(DEFAULT_CLOCK)


def next_seq():
    global _seq
    _seq += 1
    return _seq


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def clock_iso():
    return format_dt(_clock)


def new_entity():
    """Create a base entity dict with common server-managed fields."""
    ts = clock_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """Register a mutation: refresh updated_at and bump version."""
    entity["updated_at"] = clock_iso()
    entity["version"] += 1


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sort_key(entity):
    return (entity["created_at"], entity["_seq"])
