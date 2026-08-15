"""In-memory data store, logical clock, id/timestamp helpers, dirty tracking.

Storage is purely in-memory module state. Every start.sh re-invocation wipes it.
No entities are seeded at startup.
"""
import itertools
import uuid
from datetime import datetime, timezone, date

from flask import g

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Entity collections (dicts keyed by id)
# ---------------------------------------------------------------------------
db = {
    "buses": {},
    "pm_policies": {},
    "mechanics": {},
    "certifications": {},
    "shifts": {},
    "assignments": {},
    "parts": {},
    "work_orders": {},
    "part_lines": {},
    "defects": {},
    "campaigns": {},
    "logs": {},
    "inspections": {},
    "claims": {},
    "plans": {},
}

meta = {
    "clock": _DEFAULT_CLOCK,
    "epoch_index": 0,
    # cached fleet posture; None means never computed (treated as vacuous GREEN)
    "posture": None,
}

_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Clock helpers
# ---------------------------------------------------------------------------
def clock_now():
    return meta["clock"]


def set_clock(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    meta["clock"] = dt.astimezone(timezone.utc)


def clock_date():
    return meta["clock"].date()


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_ts(clock_now())


def fmt_date(d):
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


# ---------------------------------------------------------------------------
# Common fields
# ---------------------------------------------------------------------------
def init_common(entity):
    ts = now_iso()
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def mark_dirty(coll, eid):
    """Mark an existing entity as mutated in this request; version/updated_at
    are bumped once per entity per request at successful teardown."""
    try:
        dirty = g.get("dirty", None)
        if dirty is None:
            dirty = set()
            g.dirty = dirty
        dirty.add((coll, eid))
    except RuntimeError:
        # outside request context (should not happen)
        pass


def apply_dirty_bumps():
    try:
        dirty = g.get("dirty", None)
    except RuntimeError:
        return
    if not dirty:
        return
    ts = now_iso()
    for coll, eid in dirty:
        ent = db[coll].get(eid)
        if ent is not None:
            ent["version"] = int(ent.get("version", 1)) + 1
            ent["updated_at"] = ts
