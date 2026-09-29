"""In-memory data store.

Storage is plain Python dictionaries only.  The store starts completely empty
on every boot: nothing is seeded, preloaded, registered or hardcoded here.
Every entity any client needs is constructed through the declared API surface.
"""
import itertools
import uuid

import clock

engineers = {}
ahj_reviewers = {}
projects = {}
hazard_areas = {}
flow_tests = {}
evaluations = {}
calculations = {}
iterations = {}
pumps = {}
aux_systems = {}
shop_drawings = {}
trade_clearances = {}
submittals = {}
review_comments = {}
acceptance_tests = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def stamp_create(row, common_fields=True):
    """Attach id, created_at and (optionally) updated_at / version."""
    row["id"] = new_id()
    ts = clock.now_iso()
    row["created_at"] = ts
    if common_fields:
        row["updated_at"] = ts
        row["version"] = 1
    row["_seq"] = next_seq()
    return row


def snapshot(row):
    """Public field snapshot excluding the revision bookkeeping fields."""
    return {
        k: (list(v) if isinstance(v, list) else v)
        for k, v in row.items()
        if not k.startswith("_") and k not in ("updated_at", "version")
    }


def touch(row):
    """Advance updated_at and version by exactly one (PRD 2.4)."""
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 0) + 1


def touch_if_changed(row, before):
    """Advance the revision counter only when the row actually changed."""
    if snapshot(row) != before:
        touch(row)
        return True
    return False


def sort_key(row):
    return (row.get("created_at", ""), row.get("_seq", 0))


def by_created(rows):
    return sorted(rows, key=sort_key)
