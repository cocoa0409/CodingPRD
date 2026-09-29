"""In-memory storage.

Plain dicts keyed by uuid string.  Empty on every boot: nothing is seeded,
preloaded or hardcoded — all state arrives through the declared endpoints.
"""
import itertools
import uuid

import clock

TABLES = (
    "projects",
    "influent_profiles",
    "treatment_objectives",
    "process_technologies",
    "material_specs",
    "treatment_stages",
    "equipment_packages",
    "skids",
    "test_bays",
    "fat_runs",
    "or_equal_submittals",
    "spec_deviations",
    "performance_demos",
    "service_agreements",
    "consumable_draws",
)

store = {name: {} for name in TABLES}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def table(name):
    return store[name]


def get(name, row_id):
    if not isinstance(row_id, str):
        return None
    return store[name].get(row_id)


def insert(name, row):
    store[name][row["id"]] = row
    return row


def all_rows(name):
    return list(store[name].values())


def new_row(name, common_fields=True):
    """Allocate a row skeleton with its id / audit columns already stamped."""
    row = {"id": new_id(), "_seq": next_seq(), "created_at": clock.now_iso()}
    if common_fields:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Bump updated_at + version at most once per row per request."""
    if row is None:
        return None
    try:
        from flask import g
        seen = getattr(g, "_touched", None)
        if seen is None:
            seen = set()
            g._touched = seen
        key = id(row)
        if key in seen:
            return row
        seen.add(key)
    except RuntimeError:
        pass
    if "version" in row:
        row["version"] = row.get("version", 1) + 1
    if "updated_at" in row:
        row["updated_at"] = clock.now_iso()
    return row


def order_key(row, fields):
    """Sort key honouring the declared ordering plus the insertion tiebreak."""
    key = []
    for field, direction in fields:
        value = row.get(field)
        key.append(_Cmp(value, direction))
    key.append(_Cmp(row.get("_seq", 0), "asc"))
    return tuple(key)


class _Cmp:
    """Wrapper giving None-safe, direction-aware comparison."""

    __slots__ = ("value", "desc")

    def __init__(self, value, direction):
        self.value = value
        self.desc = direction == "desc"

    def _rank(self):
        v = self.value
        if v is None:
            return (0, 0)
        if isinstance(v, bool):
            return (1, int(v))
        if isinstance(v, (int, float)):
            return (1, float(v))
        return (2, str(v))

    def __eq__(self, other):
        return self._rank() == other._rank()

    def __lt__(self, other):
        a, b = self._rank(), other._rank()
        if a == b:
            return False
        return (b < a) if self.desc else (a < b)


def sorted_rows(rows, fields):
    return sorted(rows, key=lambda r: order_key(r, fields))
