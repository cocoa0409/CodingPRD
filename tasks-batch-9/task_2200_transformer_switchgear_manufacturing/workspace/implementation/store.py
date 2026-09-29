"""In-memory storage (PRD 2.4).

Storage is process-local Python dicts keyed by id. Nothing is persisted, nothing
is seeded: every entity is created by callers through the declared endpoints.
"""
import itertools
import uuid

import clock

FAMILIES = (
    "order",
    "drawing",
    "clause",
    "adjustment",
    "index_point",
    "supplier",
    "component",
    "allocation",
    "bay",
    "fat",
    "party",
    "assignment",
    "report",
    "label",
    "release",
    "storage",
    "job",
    "punch",
    "claim",
    "failure_report",
)

# CommodityIndexPoint (index_point) is the only tier-2 entity: id + created_at
# only, no updated_at, no version, never participates in OCC.
UNVERSIONED = {"index_point"}

db = {}
_seq = itertools.count(1)


def reset():
    global _seq
    _seq = itertools.count(1)
    for fam in FAMILIES:
        db[fam] = {}
    clock.reset()


def new_id():
    return str(uuid.uuid4())


def insert(family, obj):
    """Stamp identity/audit fields and store. Returns the stored object."""
    obj["id"] = obj.get("id") or new_id()
    obj["created_at"] = clock.now_str()
    if family not in UNVERSIONED:
        obj["updated_at"] = obj["created_at"]
        obj["version"] = 1
    obj["_seq"] = next(_seq)
    db[family][obj["id"]] = obj
    return obj


def touch(family, obj):
    """Record a mutation: bump version, refresh updated_at."""
    if family not in UNVERSIONED:
        obj["version"] = obj.get("version", 1) + 1
        obj["updated_at"] = clock.now_str()
    return obj


def get(family, oid):
    if oid is None:
        return None
    return db[family].get(oid)


def all_rows(family):
    return sorted(db[family].values(), key=lambda r: (r.get("created_at"), r.get("_seq", 0)))


def where(family, **filters):
    out = []
    for row in all_rows(family):
        match = True
        for k, v in filters.items():
            if row.get(k) != v:
                match = False
                break
        if match:
            out.append(row)
    return out


def public(obj):
    """Strip internal bookkeeping keys from a stored row."""
    if obj is None:
        return None
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]


reset()
