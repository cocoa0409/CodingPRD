"""In-memory data store.

Storage is Python dicts keyed by id.  The store starts completely EMPTY on
every boot: nothing is seeded, preloaded or hardcoded.  Every entity a test
needs is built through the declared API surface.
"""
from __future__ import annotations

import threading
import uuid

from flask import g

from util import CLOCK_DEFAULT_ISO, fmt_iso, parse_iso

COLLECTIONS = (
    "programs",
    "cohorts",
    "curriculum_modules",
    "facilities",
    "instructors",
    "class_sessions",
    "trainees",
    "module_completions",
    "credentials",
    "equipment_assets",
    "equipment_issuances",
    "exercises",
    "exercise_participations",
    "activations",
    "roster_assignments",
)


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.clock = parse_iso(CLOCK_DEFAULT_ISO)
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_iso(self.clock)


store = Store()


# --------------------------------------------------------------------------
# Row lifecycle
# --------------------------------------------------------------------------
def new_row(kind, **fields):
    """Create a row with the four common fields (PRD 2.4)."""
    stamp = store.now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    row.update(fields)
    row["_type"] = kind
    row["_seq"] = store.next_seq()
    return row


def _touched_set():
    s = getattr(g, "_touched_rows", None)
    if s is None:
        s = set()
        g._touched_rows = s
    return s


def touch(row):
    """Refresh updated_at and increment version — once per row per request.

    PRD 2.10: 'Every row touched anywhere in such a chain has its updated_at
    refreshed and its version incremented, exactly as if it had been modified
    directly.'  A single request bumps a given row exactly once, however many
    of its fields the cascade rewrites.
    """
    if row is None:
        return row
    row["updated_at"] = store.now_iso()
    key = (row.get("_type"), row.get("id"))
    seen = _touched_set()
    if key not in seen:
        seen.add(key)
        row["version"] = int(row.get("version", 0)) + 1
    return row


def serialize(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def serialize_many(rows):
    return [serialize(r) for r in rows]


def sorted_rows(rows):
    """PRD 2.3: list results are always ordered by created_at ascending.

    Rows minted at the same logical instant keep their insertion order, which
    is what 'created_at ascending' means for a clock that only moves on
    request.
    """
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq", 0)))


def all_rows(collection):
    return sorted_rows(list(collection.values()))
