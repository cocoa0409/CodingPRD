"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid

from response import now_iso

# One dict per entity type, keyed by id. All start empty.
operators = {}
aircraft = {}
fuel_contracts = {}
service_visits = {}
parking_spots = {}
parking_assignments = {}
fuel_orders = {}
into_plane_tickets = {}
ramp_services = {}
ramp_slots = {}
invoices = {}

# Monotonic creation counter so list ordering by created_at is stable even
# when two resources are minted within the same millisecond.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def common_create():
    """Return the common server-managed fields for a freshly created resource
    (PRD §2.4): id, created_at, updated_at, version."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(record):
    """Every mutation refreshes updated_at and increments version (PRD §2.8)."""
    record["updated_at"] = now_iso()
    record["version"] = record["version"] + 1


def public(record):
    """Strip internal-only fields from a record before returning it."""
    return {k: v for k, v in record.items() if not k.startswith("_")}
