"""In-memory data store.

Everything lives in plain Python dicts held in this module. There is no
database, no file, no cache: a fresh process starts with an empty store, which
is exactly what the per-test-server harness relies on.
"""

import uuid

from clockutil import clock, parse_iso

# Entity kinds. Each maps to an ordered dict of id -> row.
KINDS = (
    "worker",
    "patient",
    "instrument",
    "screening",
    "org",
    "offering",
    "criterion",
    "referral",
    "visit",
    "goal",
    "encounter",
    "claim",
    "award",
    "chargeline",
    "escalation",
)

# Path-collection segment -> entity kind, used by the ladder for path resolution.
tables = {kind: {} for kind in KINDS}

_seq = {"n": 0}


def _touched_set():
    """Rows already version-bumped during the current request.

    PRD §2.11: "every touched row's version increments by 1" — once per request,
    however many links of a cascade write to it.
    """
    try:
        from flask import g, has_request_context
        if has_request_context():
            if not hasattr(g, "_touched_rows"):
                g._touched_rows = set()
            return g._touched_rows
    except Exception:            # pragma: no cover - defensive
        pass
    return _fallback_touched


_fallback_touched = set()


def reset():
    for kind in KINDS:
        tables[kind].clear()
    _seq["n"] = 0
    _fallback_touched.clear()


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def insert(kind, fields):
    """Create a row with the common system fields and store it."""
    stamp = clock.now_millis()
    row = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_kind": kind,
        "_seq": next_seq(),
    }
    row.update(fields)
    tables[kind][row["id"]] = row
    # A row created by this request is born at version 1 and is not bumped again
    # by later links of the same request.
    _touched_set().add(row["id"])
    return row


def touch(row):
    """Record a mutation: bump ``version`` and refresh ``updated_at``."""
    if row is None:
        return None
    touched = _touched_set()
    if row["id"] in touched:
        row["updated_at"] = clock.now_millis()
        return row
    touched.add(row["id"])
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = clock.now_millis()
    return row


def get(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return tables[kind].get(row_id)


def _sort_key(row):
    parsed = parse_iso(row.get("created_at"))
    return (parsed, row.get("_seq", 0))


def all_rows(kind):
    """Every row of a kind in created_at ascending order (insertion breaks ties)."""
    return sorted(tables[kind].values(), key=_sort_key)


def sort_created(rows):
    return sorted(rows, key=_sort_key)


def find(kind, **filters):
    out = []
    for row in all_rows(kind):
        ok = True
        for key, value in filters.items():
            if row.get(key) != value:
                ok = False
                break
        if ok:
            out.append(row)
    return out
