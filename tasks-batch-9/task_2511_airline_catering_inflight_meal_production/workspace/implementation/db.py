"""In-memory data store.

Nothing is seeded, preloaded or hardcoded: every collection starts empty on
every boot and is only ever filled through the declared API surface.
"""

import itertools
import uuid

from flask import g, has_request_context

import clock
from timeutil import fmt_ms

COLLECTIONS = (
    "airlines",
    "meal_specifications",
    "flights",
    "special_meal_orders",
    "production_batches",
    "haccp_checks",
    "carts",
    "cart_items",
    "loading_manifests",
    "trucks",
    "stands",
    "delivery_runs",
    "uplift_records",
    "waste_manifests",
    "audit_findings",
)

store = {name: {} for name in COLLECTIONS}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def insert(collection, row, common=True):
    """Insert a row, minting the system-owned common fields.

    HaccpCheck carries only id and created_at (PRD 2.5); every other entity
    also carries updated_at and version.
    """
    now = clock.now()
    row["id"] = row.get("id") or new_id()
    row["_seq"] = next(_seq)
    row["_ct"] = now
    row["created_at"] = fmt_ms(now)
    if common:
        row["updated_at"] = fmt_ms(now)
        row["version"] = 1
    store[collection][row["id"]] = row
    return row


def touch(row, count=1):
    """Record a mutation: bump version and refresh updated_at.

    PRD 2.5 says a mutation increments `version` by *exactly* 1, and PRD 2.9
    says a cascade-reached row is treated as a real mutation. A single request
    can reach the same row down two different hops (a delay both retimes the
    flight and, through the reslot cascade, pulls it back from LOADED to
    PLANNED), so the bump is applied at most once per row per request; the
    updated_at refresh is idempotent and always applied.
    """
    if has_request_context():
        seen = getattr(g, "_touched_versions", None)
        if seen is None:
            seen = set()
            g._touched_versions = seen
        key = row.get("id")
        if key is not None:
            if key in seen:
                row["updated_at"] = fmt_ms(clock.now())
                return row
            seen.add(key)
    for _ in range(count):
        row["version"] = row.get("version", 0) + 1
    row["updated_at"] = fmt_ms(clock.now())
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return store[collection].get(row_id)


def rows(collection):
    """All rows of a collection in creation order."""
    return sorted(store[collection].values(), key=lambda r: (r["_ct"], r["_seq"]))


def where(collection, **filters):
    out = []
    for row in rows(collection):
        if all(row.get(k) == v for k, v in filters.items()):
            out.append(row)
    return out


def reset():
    for name in COLLECTIONS:
        store[name].clear()
