"""In-memory data store. The store starts empty on every boot; no seeding.
Every entity any test needs is constructed through the declared API surface."""
import itertools
import uuid

from clock import CLOCK, format_ms

DB = {
    "developers": {},
    "cluster_groups": {},
    "projects": {},
    "deposit_transactions": {},
    "milestone_submissions": {},
    "studies": {},
    "cost_shares": {},
    "agreements": {},
    "curtailment_limits": {},
    "transparency_reports": {},
}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion counter; tie-breaks created_at ordering."""
    return next(_seq)


def stamp_new(obj):
    """Common fields for mutable resources: created_at / updated_at / version."""
    ts = format_ms(CLOCK.now())
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def stamp_new_immutable(obj):
    """DepositTransaction / CurtailmentLimit / TransparencyReport carry only
    id and created_at; updated_at and version are absent entirely (PRD 2.4)."""
    obj["created_at"] = format_ms(CLOCK.now())
    return obj


def touch(obj):
    """Any mutation refreshes updated_at and increments version by one."""
    obj["updated_at"] = format_ms(CLOCK.now())
    obj["version"] = obj.get("version", 1) + 1
    return obj


def pub(obj):
    """Public view of a record: internal bookkeeping keys (underscore-prefixed)
    are never serialized."""
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def sort_key(obj):
    return (obj["created_at"], obj["_seq"])
