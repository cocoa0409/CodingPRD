"""In-memory data store.

The store starts EMPTY on every boot. Tests build all preconditions via the
declared API surface. No seeding occurs at startup.
"""
import itertools
import uuid

import clock

# Resource collections keyed by id.
membership_plans = {}
customers = {}
technicians = {}
inspectors = {}
flat_rate_items = {}
parts = {}
truck_stock = {}
service_jobs = {}
dispatch_assignments = {}
estimates = {}
estimate_lines = {}
permits = {}
inspection_visits = {}
invoices = {}
callbacks = {}

# Monotonic sequence so that creation order (and therefore created_at ascending
# sort) is stable even when the test-driven clock returns identical instants.
_seq = itertools.count(1)


def reset():
    for d in (membership_plans, customers, technicians, inspectors,
              flat_rate_items, parts, truck_stock, service_jobs,
              dispatch_assignments, estimates, estimate_lines, permits,
              inspection_visits, invoices, callbacks):
        d.clear()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def base_fields(common=True):
    """Return the system-managed fields for a new resource.

    common=True  -> id, created_at, updated_at, version (versioned resources)
    common=False -> id, created_at only (immutable config resources)
    """
    ts = clock.now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and bump version on a mutation (versioned resources)."""
    rec["updated_at"] = clock.now_iso()
    rec["version"] = rec.get("version", 1) + 1


# Fields that are internal bookkeeping and must never be serialized out.
_INTERNAL_PREFIX = "_"


def public(rec):
    """Serialize a record, dropping internal (_-prefixed) keys."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith(_INTERNAL_PREFIX)}
