"""In-memory data store.

Every collection starts empty on each boot; nothing is seeded, preloaded or
hardcoded.  All rows are created by callers through the declared endpoints.
"""

import uuid

import clock

program_years = {}
applicants = {}
applications = {}
inspections = {}
write_ups = {}
work_items = {}
contractors = {}
solicitations = {}
bids = {}
loans = {}
draw_requests = {}
change_orders = {}
complaints = {}

_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def new_row(versioned=True):
    """Mint a row carrying the common system fields (PRD 2.5)."""
    stamp = clock.now()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "_seq": _next_seq(),
    }
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Refresh updated_at to the current logical instant and bump version."""
    row["updated_at"] = clock.now()
    row["version"] = row.get("version", 1) + 1
    return row


def ordered(rows):
    """Collections are returned in ascending created_at order (PRD 2.4)."""
    return sorted(rows, key=lambda row: (row["created_at"], row["_seq"]))
