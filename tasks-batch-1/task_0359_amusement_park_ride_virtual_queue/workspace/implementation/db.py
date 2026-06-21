"""In-memory data store.

All entity data lives in plain dicts keyed by UUID id. The store starts EMPTY on
every process boot — nothing is seeded, preloaded, or hardcoded. Tests build all
preconditions via the declared API surface. start.sh re-invocation produces a fresh
process, which re-imports this module and resets every dict.

Common server-managed fields (PRD §2.4): id (UUID, no prefix), created_at,
updated_at (ISO 8601 UTC, 3 fractional digits), version (int starting at 1,
incremented on every mutation).
"""
import itertools
import uuid
from datetime import datetime, timezone

# One dict per entity type, keyed by id.
parks = {}
rides = {}
return_windows = {}
guests = {}
parties = {}
party_memberships = {}
entitlement_plans = {}
guest_day_tickets = {}
reservations = {}
lightning_lane_purchases = {}

# Monotonic creation sequence so list sort by created_at is stable even when two
# resources share the same millisecond timestamp.
_seq = itertools.count(1)


def now_iso():
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def stamp_new(record):
    """Attach common fields to a freshly created record."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next(_seq)
    return record


def touch(record):
    """Mark a record mutated: refresh updated_at and bump version (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
