"""In-memory data store. Every byte of state is wiped on each fresh boot.

No seeding, no persistence — tests build all state via the API surface.
"""
import itertools
import uuid

import clock

# One dict per entity type, keyed by id.
policyholders = {}
risk_zones = {}
repair_shops = {}
policies = {}
scheduled_items = {}
appraisals = {}
endorsements = {}
claims = {}
repair_orders = {}
premium_payments = {}

# Monotonic creation sequence so list ordering by created_at is stable even
# when two records share the same wall-clock millisecond.
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def stamp_create(record):
    """Populate system fields on a freshly created mutable resource."""
    ts = _wall_now_iso()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Mutation bump: refresh updated_at and increment version in lockstep."""
    record["updated_at"] = _wall_now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def _wall_now_iso():
    # created_at/updated_at are server-minted real timestamps (ISO 8601 UTC,
    # three fractional digits). They are independent of the logical clock.
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
