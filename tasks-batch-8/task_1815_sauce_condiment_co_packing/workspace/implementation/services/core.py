"""Shared record plumbing: creation stamps, mutation touches, serialization,
finders, and list helpers (PRD §2.4)."""
import uuid
from datetime import datetime, timezone

from db import STORE
from errors import err


def now():
    return datetime.now(timezone.utc)


def new_record(fields):
    """Stamp a fresh entity dict with the system common fields (§2.4)."""
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = now()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = STORE.next_seq()
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (§2.4)."""
    rec["version"] += 1
    rec["updated_at"] = now()


def serialize(rec):
    """Public view: drop internal '_' keys, render datetimes as ISO-8601 UTC
    with three fractional digits."""
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt(v)
        else:
            out[k] = v
    return out


def fmt(dt):
    from util import fmt_ts
    return fmt_ts(dt)


def find_or_404(table, rid, error_id, what="resource"):
    rec = table.get(rid)
    if rec is None:
        raise err(error_id, 404, f"{what} does not exist")
    return rec


def sorted_created(items):
    """List endpoints sort by creation timestamp ascending (§2.3); the
    monotonic sequence breaks ties deterministically."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
