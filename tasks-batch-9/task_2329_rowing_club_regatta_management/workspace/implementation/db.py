"""In-memory storage. Plain Python dicts; nothing is ever persisted to disk and
no data is ever seeded at startup."""
import itertools
import uuid

from flask import g

import clock

members = {}
invoices = {}
shells = {}
reports = {}
readings = {}
sessions = {}
regattas = {}
entries = {}
seats = {}
heats = {}
lanes = {}
protests = {}
trailers = {}

STORES = (members, invoices, shells, reports, readings, sessions, regattas,
          entries, seats, heats, lanes, protests, trailers)

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def _touched():
    try:
        bag = g._touched
    except (AttributeError, RuntimeError):
        bag = None
    if bag is None:
        bag = set()
        try:
            g._touched = bag
        except RuntimeError:
            pass
    return bag


def base_record(versioned=True):
    """A fresh row: id, created_at and (unless the entity is immutable) updated_at
    plus version == 1. The row is registered as already-touched so that a cascade
    inside the very same request cannot push a brand-new row to version 2."""
    now = clock.now()
    rec = {"id": new_id(), "_seq": next_seq()}
    rec["created_at"] = clock.fmt(now)
    rec["_created_at"] = now
    if versioned:
        rec["updated_at"] = clock.fmt(now)
        rec["_updated_at"] = now
        rec["version"] = 1
    _touched().add(rec["id"])
    return rec


def touch(rec):
    """Refresh updated_at and increment version, at most once per request per row."""
    if rec is None or "version" not in rec:
        return rec
    bag = _touched()
    if rec["id"] in bag:
        return rec
    bag.add(rec["id"])
    now = clock.now()
    rec["updated_at"] = clock.fmt(now)
    rec["_updated_at"] = now
    rec["version"] = rec["version"] + 1
    return rec


def set_dt(rec, field, value, raw=None):
    """Store a datetime twice: the wire representation under `field` (verbatim when
    the client supplied it) and the parsed value under `_field` for comparisons."""
    if value is None:
        rec[field] = None
        rec["_" + field] = None
    else:
        rec[field] = raw if raw is not None else clock.fmt(value)
        rec["_" + field] = value
    return rec


def dt(rec, field):
    return rec.get("_" + field)


def ordered(store, predicate=None):
    rows = [r for r in store.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["_created_at"], r["_seq"]))
    return rows


def reset_all():
    for store in STORES:
        store.clear()
