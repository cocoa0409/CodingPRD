"""In-memory data store.

All state lives in process memory only (Python dicts). Nothing is persisted
and nothing is seeded at startup — every entity is created by tests through the
declared API surface. A fresh process therefore starts entirely empty.
"""
import threading
import uuid

import clock
from timeutil import iso_z

_lock = threading.RLock()

# One dict per entity type, keyed by id.
borrowers = {}
abs_pools = {}
rate_grid_entries = {}
applications = {}
offers = {}
cosigners = {}
loans = {}
disbursements = {}
payments = {}
forbearance_plans = {}
audit_events = []  # append-only ordered list

# Monotonic creation sequence — a stable secondary sort key so records created
# within the same millisecond (e.g. a burst of offers at prequalify) keep their
# true creation order under the created_at ascending sort (PRD §2.3).
_seq = [0]


def next_seq():
    with _lock:
        _seq[0] += 1
        return _seq[0]


def lock():
    return _lock


def reset():
    """Wipe all state. Used for a clean slate; the store also starts empty."""
    with _lock:
        borrowers.clear()
        abs_pools.clear()
        rate_grid_entries.clear()
        applications.clear()
        offers.clear()
        cosigners.clear()
        loans.clear()
        disbursements.clear()
        payments.clear()
        forbearance_plans.clear()
        audit_events.clear()
        _seq[0] = 0
        clock.reset()


def new_id():
    """Server-minted opaque UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def stamp_create(record, with_version=True):
    """Set id + common managed fields on a brand-new record (PRD §2.4).

    created_at/updated_at are ISO 8601 UTC with three fractional digits;
    version begins at 1. Light entities (RateGridEntry, AuditEvent) pass
    with_version=False so they carry only id + created_at.
    """
    now = clock.now()
    record["id"] = new_id()
    record["created_at"] = iso_z(now)
    record["_seq"] = next_seq()
    if with_version:
        record["updated_at"] = iso_z(now)
        record["version"] = 1
    return record


def touch(record):
    """Bump a mutated record: increment version, refresh updated_at (PRD §2.4)."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = iso_z(clock.now())
    return record
