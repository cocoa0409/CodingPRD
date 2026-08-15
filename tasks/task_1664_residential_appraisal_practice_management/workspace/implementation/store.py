"""In-memory store.  Plain dicts keyed by id; nothing is persisted to disk
and nothing is seeded at import time - every row is built by a declared
endpoint.  Restarting the process wipes every byte of state."""

import uuid

from timeutil import clock, render_instant

# ------------------------------------------------------------------ collections
clients = {}
appraisers = {}
panel_memberships = {}
fee_schedules = {}
orders = {}
appointments = {}
comparables = {}
reports = {}
revision_requests = {}
workfile_records = {}
complaints = {}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def now_string():
    return clock.now_string()


def new_row(collection, **fields):
    row = {"id": new_id()}
    ts = now_string()
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_created_dt"] = clock.now
    row["_seq"] = next_seq()
    row.update(fields)
    collection[row["id"]] = row
    return row


def touch(row):
    """PRD 2.5/2.10: every modification increments version by exactly one and
    refreshes updated_at."""
    row["version"] += 1
    row["updated_at"] = now_string()


def order_key(row):
    return (row["_created_dt"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=order_key)


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]
