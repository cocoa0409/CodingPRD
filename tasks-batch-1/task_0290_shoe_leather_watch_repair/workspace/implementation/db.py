"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts EMPTY on every process boot. No seeding, no preload — every
entity is created by tests via the declared API surface. start.sh re-invocation
wipes all state by virtue of being a fresh process.
"""
import uuid
import clock

# Collections keyed by id (insertion order preserved -> creation order)
customers = {}
service_types = {}
technicians = {}
repair_tickets = {}
ticket_items = {}
service_lines = {}
estimates = {}
parts_orders = {}
payments = {}
warranty_claims = {}
notifications = {}

# monotonically increasing sequence to break ties deterministically by creation
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def stamp_create(record):
    """Attach standard system fields for a versioned entity at create time."""
    ts = clock.now()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def stamp_audit_create(record):
    """Attach fields for an append-only audit entity (id + created_at only)."""
    record["created_at"] = clock.now()
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Bump version + updated_at on mutation of a versioned entity."""
    record["updated_at"] = clock.now()
    record["version"] = record.get("version", 1) + 1
    return record
