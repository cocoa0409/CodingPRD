"""In-memory data store.

PRD §2.4: every resource carries a system-minted UUID `id` (no type prefix),
a `created_at`, an `updated_at`, and an integer `version` that begins at its
initial value on creation and increments by one on every mutation.

The store starts EMPTY on every boot. Nothing is seeded — every entity any
test needs is constructed by the test via the declared endpoints.
"""

import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Entity tables — one dict per entity, keyed by id.
# ---------------------------------------------------------------------------
shops = {}
products = {}
pricing_tiers = {}
finishing_options = {}
customers = {}
orders = {}
order_lines = {}
artworks = {}
proofs = {}
fulfillments = {}
presses = {}
press_bookings = {}
capacity_reservations = {}

# Monotonic creation counter so list sort by created_at is stable even when two
# resources share the same wall-clock millisecond (PRD §2.3 sort by created_at asc).
_seq = 0

# Pinnable system clock (PRD §3.9 /_clock/set_current_utc). None => real wall clock.
_pinned_utc = None


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def next_seq():
    global _seq
    _seq += 1
    return _seq


def set_clock(iso_str):
    """Pin the system clock (PRD §3.9). Stored verbatim; returned as current_utc."""
    global _pinned_utc
    _pinned_utc = iso_str


def current_utc():
    """The current UTC instant the system is operating against (PRD §3.6/§3.9).

    Returns the pinned value if set, else the real wall clock in ISO 8601 UTC.
    """
    if _pinned_utc is not None:
        return _pinned_utc
    return now_iso()


def reset():
    """Clear all state. (Not called at boot — store is naturally empty.)"""
    global _seq, _pinned_utc
    for table in (
        shops, products, pricing_tiers, finishing_options, customers,
        orders, order_lines, artworks, proofs, fulfillments, presses,
        press_bookings, capacity_reservations,
    ):
        table.clear()
    _seq = 0
    _pinned_utc = None


def stamp_new(record, initial_version=1):
    """Attach system common fields on create (PRD §2.4)."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = initial_version
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Register a mutation: bump version, refresh updated_at (PRD §2.4)."""
    record["version"] += 1
    record["updated_at"] = now_iso()
    return record
