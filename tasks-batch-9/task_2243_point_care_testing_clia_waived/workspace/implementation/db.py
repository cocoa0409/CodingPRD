"""In-memory data store.

Starts empty on every boot.  Nothing is seeded here or anywhere else.
"""

import itertools
import uuid

import clock

TABLES = (
    "certificates",
    "sites",
    "coverages",
    "operators",
    "assessments",
    "devices",
    "storage_units",
    "temp_readings",
    "lots",
    "qc_runs",
    "results",
    "enrollments",
    "pt_events",
    "inspections",
    "findings",
)

data = {name: {} for name in TABLES}

_seq = itertools.count(1)


def reset():
    global _seq
    for name in TABLES:
        data[name] = {}
    _seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def insert(table, fields, common=True):
    """Create a row with the system fields (PRD 2.4) and store it."""
    row = {
        "id": new_id(),
        "_seq": next(_seq),
        "_common": common,
    }
    row.update(fields)
    row["created_at"] = clock.now_iso()
    if common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    data[table][row["id"]] = row
    return row


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return data[table].get(row_id)


def rows(table):
    """All rows of a table in created_at ASC order (insertion order breaks ties)."""
    return sorted(data[table].values(), key=lambda r: (r["created_at"], r["_seq"]))


def all_rows(table):
    """Raw insertion order — used for chronological (seq) comparisons."""
    return sorted(data[table].values(), key=lambda r: r["_seq"])


def snapshot(row):
    return {k: v for k, v in row.items()
            if k not in ("updated_at", "version", "_seq", "_common")}


def touch(row):
    """Unconditional mutation stamp."""
    if not row.get("_common", True):
        return
    row["updated_at"] = clock.now_iso()
    row["version"] = row.get("version", 1) + 1


def touch_if_changed(row, snap):
    """Stamp the row only when one of its persisted values actually moved."""
    if not row.get("_common", True):
        return False
    if snapshot(row) != snap:
        touch(row)
        return True
    return False


def earlier(a, b):
    """Chronological strict-before test for two rows of the same table.

    created_at is the primary key; insertion sequence disambiguates rows created
    at the same logical instant (the logical clock does not advance by itself).
    """
    return (a["created_at"], a["_seq"]) < (b["created_at"], b["_seq"])
