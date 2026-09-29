"""In-memory data store, logical clock and per-request version bookkeeping.

The store always starts EMPTY.  No entity is ever seeded, preloaded or
hardcoded at import time -- every record is created through the declared
API surface.
"""

import copy
import itertools
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import g

from response import wall_now_iso

# ---------------------------------------------------------------- collections

KINDS = (
    "program",
    "abstractor",
    "source",
    "entry",
    "case",
    "contact",
    "abstraction",
    "audit",
    "session",
    "submission",
    "item",
    "deficiency",
    "measure",
)

store = {k: {} for k in KINDS}

_seq = itertools.count(1)

# ------------------------------------------------------------- logical clock

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": CLOCK_DEFAULT}


def clock_now():
    return _clock["now"]


def clock_date():
    return _clock["now"].date()


def set_clock(instant):
    _clock["now"] = instant


def reset_all():
    for k in KINDS:
        store[k].clear()
    _clock["now"] = CLOCK_DEFAULT


# ------------------------------------------------------------- time helpers

def fmt_instant(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    if d is None:
        return None
    return d.isoformat()


def parse_date(value):
    """Strict ISO 8601 calendar date."""
    if not isinstance(value, str):
        return None
    if len(value) != 10 or value[4] != "-" or value[7] != "-":
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except (ValueError, TypeError):
        return None


def parse_instant(value):
    """Strict-ish ISO 8601 UTC instant."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days_between(start, end):
    """Whole calendar days from start to end (end - start)."""
    return (end - start).days


def add_days(d, n):
    return d + timedelta(days=n)


def month_bounds(d):
    first = date(d.year, d.month, 1)
    if d.month == 12:
        nxt = date(d.year + 1, 1, 1)
    else:
        nxt = date(d.year, d.month + 1, 1)
    return first, nxt - timedelta(days=1)


# ----------------------------------------------------------- entity plumbing

def _tracked_view(obj):
    return {k: copy.deepcopy(v) for k, v in obj.items()
            if not k.startswith("_") and k not in ("updated_at", "version")}


def _fresh_ids():
    ids = getattr(g, "_fresh_ids", None)
    if ids is None:
        ids = set()
        g._fresh_ids = ids
    return ids


def mark(obj):
    """Register a pre-existing entity as touched by this request."""
    if obj is None:
        return obj
    dirty = getattr(g, "_dirty", None)
    if dirty is None:
        dirty = {}
        g._dirty = dirty
    key = id(obj)
    if key not in dirty and obj["id"] not in _fresh_ids():
        dirty[key] = (obj, _tracked_view(obj))
    return obj


def force_touch(obj):
    """Guarantee a version bump for this resource even if no field changed."""
    mark(obj)
    forced = getattr(g, "_forced", None)
    if forced is None:
        forced = set()
        g._forced = forced
    forced.add(id(obj))
    return obj


def commit():
    """Bump version/updated_at once per resource whose public state changed."""
    dirty = getattr(g, "_dirty", None)
    forced = getattr(g, "_forced", None) or set()
    if not dirty:
        return
    for key, (obj, before) in dirty.items():
        if "version" not in obj:
            continue
        if key in forced or _tracked_view(obj) != before:
            obj["version"] = obj["version"] + 1
            obj["updated_at"] = wall_now_iso()
    g._dirty = {}
    g._forced = set()


def new_entity(kind, fields, versioned=True):
    now = wall_now_iso()
    obj = {"id": str(uuid.uuid4()), "created_at": now}
    if versioned:
        obj["updated_at"] = now
        obj["version"] = 1
    obj.update(fields)
    obj["_seq"] = next(_seq)
    store[kind][obj["id"]] = obj
    _fresh_ids().add(obj["id"])
    return obj


def public(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def get(kind, oid):
    if not isinstance(oid, str):
        return None
    return store[kind].get(oid)


def all_of(kind):
    return sorted(store[kind].values(), key=lambda o: o["_seq"])
