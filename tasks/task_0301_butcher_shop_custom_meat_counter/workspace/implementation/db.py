"""In-memory data store (PRD §2.4, §2.8).

Every entity is a plain dict keyed by its UUID `id`. The store starts EMPTY on
every process boot — no seeding, no preloaded records. Tests construct all
preconditions through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

from response import now_iso

# One dict per entity type, keyed by id.
customers = {}
cut_types = {}
pricing_policies = {}
inventory_lots = {}
dry_age_lockers = {}
temp_readings = {}
animal_shares = {}
share_claims = {}
custom_orders = {}
order_lines = {}
lot_draws = {}
sausage_batches = {}
batch_inputs = {}
holiday_windows = {}

# Monotonic sequence to keep created_at ties deterministic in sort order.
_seq = itertools.count(1)

# Logical clock (PRD §3.9). Defaults to real wall-clock UTC until set.
_clock_override = None


def reset():
    """Clear every collection. Used at module import; store starts empty."""
    for d in (customers, cut_types, pricing_policies, inventory_lots,
              dry_age_lockers, temp_readings, animal_shares, share_claims,
              custom_orders, order_lines, lot_draws, sausage_batches,
              batch_inputs, holiday_windows):
        d.clear()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def set_clock(dt):
    global _clock_override
    _clock_override = dt


def current_utc():
    """The server's notion of 'now' (logical clock if set, else wall clock)."""
    if _clock_override is not None:
        return _clock_override
    return datetime.now(timezone.utc)


# --- Common system fields (PRD §2.4) ---

def stamp_create(record, with_version=True):
    """Attach id/created_at/updated_at/version. Logs omit version+updated_at."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = next_seq()
    if with_version:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Mark a mutation: refresh updated_at and bump version (PRD §2.4)."""
    if "version" in record:
        record["version"] += 1
        record["updated_at"] = now_iso()
    return record
