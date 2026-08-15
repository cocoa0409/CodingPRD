"""Shared record plumbing: creation stamps, mutation touches, serialization,
finders, and list helpers."""
import uuid
from datetime import datetime

from db import STORE
from errors import not_found
from util import fmt_plain, fmt_ts


def now():
    return STORE.clock


def new_record(fields):
    """Stamp a fresh entity dict with system common fields (§2.4)."""
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = STORE.clock
    rec["updated_at"] = STORE.clock
    rec["version"] = 1
    rec["_seq"] = STORE.next_seq()
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (§2.4)."""
    rec["version"] += 1
    rec["updated_at"] = STORE.clock


def serialize(rec):
    """Public view: drop internal '_' keys. System-managed created_at /
    updated_at render with three fractional digits (§2.4); every other
    (business) datetime renders in the PRD's plain seconds form (§2.5/§2.6)."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_ts(v) if k in ("created_at", "updated_at") else fmt_plain(v)
        else:
            out[k] = v
    return out


def find_or_404(table, rid, what="resource"):
    rec = table.get(rid)
    if rec is None:
        raise not_found(what)
    return rec


def sorted_created(items):
    """List endpoints sort by creation timestamp ascending (§2.3); the
    monotonic sequence breaks ties deterministically."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


def list_view(table):
    return [serialize(r) for r in sorted_created(table.values())]
