"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone

from response import now_iso

# One dict per entity type, keyed by id. All start empty.
booth_models = {}
packages = {}
booths = {}
attendants = {}
customers = {}
bookings = {}
add_ons = {}
booking_add_ons = {}
attendant_assignments = {}
payments = {}
event_logs = {}
galleries = {}

# Server logical clock (PRD §3.10). Defaults to wall-clock UTC until pinned by
# POST /_clock/set_current_utc. Stored as a timezone-aware datetime.
_clock = {"now": None}


def get_clock():
    if _clock["now"] is not None:
        return _clock["now"]
    return datetime.now(timezone.utc)


def set_clock(dt):
    _clock["now"] = dt


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


def payment_create():
    """Payment is append-only: only id and created_at, no updated_at/version
    (PRD §2.4)."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }


def touch(record):
    """Every mutation refreshes updated_at and increments version (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record["version"] + 1


def public(record):
    """Strip internal-only fields from a record before returning it."""
    return {k: v for k, v in record.items() if not k.startswith("_")}
