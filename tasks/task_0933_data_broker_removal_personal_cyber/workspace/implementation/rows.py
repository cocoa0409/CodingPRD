"""Row construction and mutation bookkeeping (PRD §2.4, §2.11)."""

import ids
from clock import CLOCK
from store import DB


def new_row(collection, fields, common=True):
    row = dict(fields)
    row["id"] = ids.new_id()
    row["created_at"] = CLOCK.now
    if common:
        row["updated_at"] = CLOCK.now
        row["version"] = 1
    DB.put(collection, row)
    return row


def touch(row):
    """Every mutation refreshes updated_at and increments version by exactly 1."""
    row["updated_at"] = CLOCK.now
    row["version"] = row["version"] + 1
    return row
