"""In-memory data store. Starts empty on every boot — no seeding."""
import itertools
import uuid

from response import now_iso

# Entity collections keyed by id.
sailings = {}
cabin_categories = {}
cabins = {}
group_blocks = {}
bookings = {}
guests = {}
add_ons = {}
dining_reservations = {}
payments = {}
folios = {}
folio_charges = {}

# Simulated current UTC clock (ISO 8601 string) — None means "not yet set".
clock_utc = None

# Monotonic counter used as a deterministic tie-breaker for created_at ordering.
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def base_fields():
    """Common system fields shared by every entity (PRD §2.4)."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """Mark an entity mutated: refresh updated_at, bump version (PRD §2.4)."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def soft_touch(entity):
    """Refresh updated_at without bumping version.

    Used for derived count/total roll-ups that happen as side effects. The
    Sailing.version contract is reserved for the explicit lifecycle transitions
    (open/close/depart/cancel) and the OCC epoch; bumping version on every
    rollup recompute would desynchronize the client's observed version and
    break optimistic-concurrency expectations.
    """
    entity["updated_at"] = now_iso()
