"""In-memory data store.

Storage is Python dictionaries only.  Nothing is seeded, preloaded or
hardcoded: every row in this store is created by a caller through a declared
endpoint, so a fresh process starts completely empty.
"""

import uuid

import clock

COLLECTIONS = [
    "program_periods",
    "sites",
    "site_holds",
    "patients",
    "consents",
    "portable_units",
    "sterilization_loads",
    "staff_members",
    "site_visits",
    "coverages",
    "encounters",
    "procedures",
    "treatment_plans",
    "referrals",
    "reports",
]

db = {name: {} for name in COLLECTIONS}

_seq = {"n": 0}


def _next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def insert(collection, row):
    """Mint a row with the four common properties at version 1."""
    instant = clock.now()
    row["id"] = row.get("id") or new_id()
    row["created_at"] = instant
    row["updated_at"] = instant
    row["version"] = 1
    row["_seq"] = _next_seq()
    db[collection][row["id"]] = row
    return row


def get(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return db[collection].get(row_id)


def all_rows(collection):
    """Every row of a collection in created_at ascending, insertion-order tie-break."""
    return sorted(db[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))


def find(collection, **predicates):
    result = []
    for row in all_rows(collection):
        ok = True
        for key, value in predicates.items():
            if row.get(key) != value:
                ok = False
                break
        if ok:
            result.append(row)
    return result


def reset():
    for name in COLLECTIONS:
        db[name] = {}
    _seq["n"] = 0
