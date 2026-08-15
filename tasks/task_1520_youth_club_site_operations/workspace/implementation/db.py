"""In-memory data store. The store starts completely empty on every boot —
no seeding, no preloading, no disk persistence of any kind."""

import uuid

import clock_util


def _empty_bucket():
    return {"rows": {}, "order": []}


# One bucket per entity type. Keys are plural store names used throughout.
STORE = {
    "sites": _empty_bucket(),
    "staff": _empty_bucket(),
    "members": _empty_bucket(),
    "guardians": _empty_bucket(),
    "funds": _empty_bucket(),
    "awards": _empty_bucket(),
    "club_days": _empty_bucket(),
    "attendance": _empty_bucket(),
    "areas": _empty_bucket(),
    "rotations": _empty_bucket(),
    "routes": _empty_bucket(),
    "rides": _empty_bucket(),
    "claims": _empty_bucket(),
    "incidents": _empty_bucket(),
    "reports": _empty_bucket(),
}


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return clock_util.CLOCK.now_iso()


def insert(kind, record):
    rid = record["id"]
    STORE[kind]["rows"][rid] = record
    STORE[kind]["order"].append(rid)
    return record


def get(kind, rid):
    return STORE[kind]["rows"].get(rid)


def all_records(kind):
    bucket = STORE[kind]
    return [bucket["rows"][rid] for rid in bucket["order"]]


def find(kind, **filters):
    out = []
    for rec in all_records(kind):
        ok = True
        for k, v in filters.items():
            if rec.get(k) != v:
                ok = False
                break
        if ok:
            out.append(rec)
    return out


def touch(record):
    """Every mutation refreshes updated_at and increments version (PRD §2.5)."""
    record["updated_at"] = now_iso()
    record["version"] += 1
