"""In-memory data store. Starts EMPTY on every boot. No seeding, ever.

Each entity type is a dict keyed by uuid string. Common fields (id, created_at,
updated_at, version) are managed here. created_at/updated_at are ISO 8601 UTC
with three fractional digits; version starts at 1 and increments on mutation.
"""
import itertools
import uuid

from response import now_iso

# One dict per entity type. Insertion order is preserved (Python 3.7+),
# giving stable created_at-ascending iteration for list endpoints.
service_areas = {}
crews = {}
equipment = {}
work_orders = {}
trees = {}
estimates = {}
line_items = {}
permits = {}
bookings = {}
disposal_tickets = {}

# Monotonic counter to break created_at ties deterministically (timestamps have
# only millisecond resolution; rapid creates can collide). Sort uses (created_at,
# _seq) so ordering matches creation order exactly.
_seq_counter = itertools.count()


def new_id():
    return str(uuid.uuid4())


def stamp_new(obj):
    """Attach common fields to a freshly created entity."""
    ts = now_iso()
    obj.setdefault("id", new_id())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    obj["_seq"] = next(_seq_counter)
    return obj


def touch(obj):
    """Mark an entity as mutated: refresh updated_at, bump version."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 1) + 1
    return obj


def sort_by_created(values):
    return sorted(values, key=lambda o: (o["created_at"], o["_seq"]))


def public(obj):
    """Strip internal-only fields (those prefixed with '_') for the response."""
    return {k: v for k, v in obj.items() if not k.startswith("_")}
