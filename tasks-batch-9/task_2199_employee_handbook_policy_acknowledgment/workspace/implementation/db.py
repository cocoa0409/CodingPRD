"""In-memory store. Dicts keyed by id. Never seeded."""
import itertools
import uuid

import clock

TABLES = [
    "jurisdictions",
    "legal_reviewers",
    "employees",
    "policy_documents",
    "policy_versions",
    "addenda",
    "legal_reviews",
    "translations",
    "release_packages",
    "release_items",
    "assignments",
    "acknowledgments",
    "escalations",
    "policy_exceptions",
    "retention_records",
]

store = {t: {} for t in TABLES}
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def seq():
    return next(_seq)


def reset():
    for t in TABLES:
        store[t] = {}
    clock.reset()


def table(name):
    return store[name]


def get(name, rid):
    if not isinstance(rid, str):
        return None
    return store[name].get(rid)


def insert(name, row):
    store[name][row["id"]] = row
    return row


def all_rows(name):
    """Rows in insertion (creation) order."""
    return list(store[name].values())


def base_row(versioned=True):
    now = clock.now()
    row = {"id": new_id(), "created_at": now, "_seq": seq()}
    if versioned:
        row["updated_at"] = now
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at from the logical clock and bump version by 1."""
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = clock.now()
    return row


def sort_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
