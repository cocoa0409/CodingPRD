"""In-memory store.  The store starts completely empty on every boot; no entity
is ever seeded, preloaded or hardcoded at startup."""

import uuid
from datetime import datetime, timezone

from flask import g

import logical_clock


def real_now():
    return datetime.now(timezone.utc)


def stamp_now():
    """PRD 2.5: nothing in this system reads real wall-clock time, so `created_at`
    and `updated_at` are stamped from the logical program clock."""
    return logical_clock.now()


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Store:
    def __init__(self):
        self.schools = {}
        self.offerings = {}
        self.alignments = {}
        self.materials = {}
        self.educators = {}
        self.training = {}
        self.permits = {}
        self.animals = {}
        self.trails = {}
        self.bookings = {}
        self.funds = {}
        self.aid = {}
        self.manifests = {}
        self.evaluations = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# --------------------------------------------------------------------------
# per-request mutation bookkeeping: a resource's `version` moves at most once
# per request no matter how many side effects touch it.
# --------------------------------------------------------------------------
def _touched():
    store = getattr(g, "_touched_ids", None)
    if store is None:
        store = set()
        g._touched_ids = store
    return store


def mark_touched(entity):
    _touched().add(id(entity))


def touch(entity):
    seen = _touched()
    if id(entity) in seen:
        return
    seen.add(id(entity))
    if "version" in entity:
        entity["version"] = entity["version"] + 1
        entity["updated_at"] = iso3(stamp_now())


def new_entity(versioned=True):
    stamp = iso3(stamp_now())
    entity = {"id": str(uuid.uuid4()), "created_at": stamp}
    if versioned:
        entity["updated_at"] = stamp
        entity["version"] = 1
    entity["_seq"] = db.next_seq()
    entity["_dt"] = {}
    mark_touched(entity)
    return entity


def set_dt(entity, field, raw, dt):
    """Store a datetime field: the payload keeps the client's literal string,
    the parsed instant is kept aside for arithmetic."""
    entity[field] = raw
    entity["_dt"][field] = dt


def set_system_dt(entity, field, dt):
    entity[field] = iso3(dt) if dt is not None else None
    entity["_dt"][field] = dt


def get_dt(entity, field):
    cached = entity.get("_dt", {})
    if field in cached:
        return cached[field]
    parsed = parse_iso(entity.get(field))
    cached[field] = parsed
    return parsed


def public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sorted_rows(rows):
    return sorted(rows, key=lambda r: r["_seq"])
