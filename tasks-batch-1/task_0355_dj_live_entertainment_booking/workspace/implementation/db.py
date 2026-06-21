"""In-memory data store.

Every entity type gets its own dict keyed by UUID id. The store starts empty on
every boot — NOTHING is seeded here. Tests build all preconditions through the
declared API surface.

A module-global monotonic sequence is attached to each record (`_seq`) to give a
stable, insertion-order tiebreak when two records share the same created_at
timestamp (timestamps have only millisecond resolution).
"""
import threading
import uuid

from clock import now
from timeutil import iso_now

LOCK = threading.RLock()

# One dict per entity, keyed by id.
performers = {}
travel_zones = {}
packages = {}
equipment_items = {}
bookings = {}
clients = {}
payments = {}
song_requests = {}
contracts = {}
backup_assignments = {}
blackout_windows = {}

_seq_counter = 0


def reset():
    """Wipe all state. Used only as a defensive helper; a fresh process already
    starts empty."""
    global _seq_counter
    for d in (performers, travel_zones, packages, equipment_items, bookings,
              clients, payments, song_requests, contracts, backup_assignments,
              blackout_windows):
        d.clear()
    _seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    # PRD: "a server-minted UUID with no type prefix" — canonical 36-char
    # dashed UUID string (not the dash-stripped .hex form).
    return str(uuid.uuid4())


def make_common(with_version=True):
    """Build the shared system-managed fields. created_at/updated_at are ISO 8601
    UTC with millisecond precision off the logical clock."""
    ts = iso_now(now())
    base = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if with_version:
        base["updated_at"] = ts
        base["version"] = 1
    return base


def touch(record):
    """Refresh updated_at and bump version by exactly 1 on a mutation.

    BlackoutWindow (no version field) is immutable and never passed here.
    """
    if "version" in record:
        record["version"] += 1
        record["updated_at"] = iso_now(now())
