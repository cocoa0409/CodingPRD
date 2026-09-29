"""Record-level helpers: the logical clock, id minting and mutation stamping."""
import uuid
from datetime import timedelta

from flask import g

from db import db


def now():
    """The current instant = the logical clock (PRD §2.4)."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def _touched():
    if not hasattr(g, "touched_records"):
        g.touched_records = set()
    return g.touched_records


def base_record(with_version=True):
    rec = {"id": new_id(), "created_at": now(), "_seq": db.next_seq()}
    if with_version:
        rec["updated_at"] = now()
        rec["version"] = 1
    return rec


def touch(rec):
    """Mark a record mutated: refresh ``updated_at`` and bump ``version`` once
    per request (PRD §2.9 — every touched record is a mutation)."""
    if rec is None or "version" not in rec:
        return rec
    key = id(rec)
    seen = _touched()
    rec["updated_at"] = now()
    if key not in seen:
        seen.add(key)
        rec["version"] = rec["version"] + 1
    return rec


def add_days(anchor, days):
    """Whole-UTC-day addition preserving the anchor's time of day (PRD §2.5)."""
    if anchor is None:
        return None
    return anchor + timedelta(days=days)


def by_seq(records):
    return sorted(records, key=lambda r: r.get("_seq", 0))
