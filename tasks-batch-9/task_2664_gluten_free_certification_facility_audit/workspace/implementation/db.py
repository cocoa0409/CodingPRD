"""In-memory store. Starts empty on every boot; no seeding, no disk state."""

import itertools
import uuid

import clock

applicants = {}
facilities = {}
suppliers = {}
supplier_documents = {}
ingredients = {}
products = {}
product_ingredients = {}
lot_tests = {}
audits = {}
certificates = {}
nonconformances = {}
change_notifications = {}
consumer_complaints = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def insert(table, row, versioned=True):
    """Stamp identity + system fields on a fresh row and store it."""
    now = clock.now()
    stamped = {"id": row.pop("id", None) or new_id()}
    stamped.update(row)
    stamped["created_at"] = now
    if versioned:
        stamped["updated_at"] = now
        stamped["version"] = 1
    stamped["_seq"] = next_seq()
    table[stamped["id"]] = stamped
    return stamped


def touch(row):
    """Record a mutation: refresh updated_at and advance version by one."""
    if row is None:
        return row
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = clock.now()
    return row


_TRACKED_SKIP = ("_seq", "updated_at", "version")


def snapshot(row):
    return {k: (list(v) if isinstance(v, list) else v)
            for k, v in row.items() if k not in _TRACKED_SKIP}


def touch_if_changed(row, before):
    """Bump version/updated_at only when the row's data actually changed."""
    if snapshot(row) != before:
        touch(row)
        return True
    return False


def ordered(table):
    """Every collection is ordered by created_at ascending (stable)."""
    return sorted(table.values(), key=lambda r: (r["created_at"], r["_seq"]))
