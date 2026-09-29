"""In-memory data store.

Every collection starts empty on every boot: no entity is ever seeded,
preloaded or hardcoded.  Tests build all preconditions through the API.
"""

import itertools
import uuid

from flask import g

import clock

camps = {}
standards_sets = {}
standards = {}
cycles = {}
evaluations = {}
written_plans = {}
visitors = {}
visits = {}
assignments = {}
deficiencies = {}
med_records = {}
annual_reports = {}
disclosures = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def common_fields():
    stamp = clock.now_iso()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": next_seq(),
    }


def touched():
    if not hasattr(g, "_touched_rows"):
        g._touched_rows = set()
    return g._touched_rows


def touch(row):
    """Mutation bookkeeping: updated_at refreshed and version incremented.

    A row is bumped at most once per request, so the endpoints that PRD 2.6
    describes as 'increments the parent's version by one' do exactly that even
    when several derived fields on the same row change in the one request.
    """
    if row is None:
        return row
    seen = touched()
    if row["id"] in seen:
        return row
    seen.add(row["id"])
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = clock.now_iso()
    return row


def ordered(collection, predicate=None):
    rows = [r for r in collection.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
