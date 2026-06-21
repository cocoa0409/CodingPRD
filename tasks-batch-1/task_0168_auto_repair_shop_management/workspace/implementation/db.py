"""In-memory data store.

All state lives in module-level dicts keyed by id. The store starts EMPTY on
every process boot — nothing is seeded. start.sh re-invocation (a fresh process)
wipes every byte of state. (per SKILL: no seeding, no persistence.)

Common fields (PRD 2.4): id (UUID, no prefix), created_at, updated_at, version.
version begins at its initial value (1) and increments by one on each mutation.
"""
import itertools
import uuid

from clock import now_iso

# One dict per entity collection, keyed by id.
customers = {}
vehicles = {}
technicians = {}
service_bays = {}
labor_operations = {}
markup_tiers = {}
repair_orders = {}
labor_lines = {}
part_lines = {}
core_charges = {}
inspections = {}
recommended_jobs = {}

# Monotonic creation sequence so list ordering by created_at is stable even when
# multiple resources share the same logical-clock timestamp (PRD 2.3 sorts by
# created_at ascending).
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def common_fields():
    """Stamp id/created_at/updated_at/version on a fresh resource."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),
    }


def touch(resource):
    """Bump updated_at + version on a mutation/cascade (PRD 2.4, 2.8)."""
    resource["updated_at"] = now_iso()
    resource["version"] = resource["version"] + 1


def public(resource):
    """Strip private bookkeeping keys (those starting with '_') for output."""
    return {k: v for k, v in resource.items() if not k.startswith("_")}
