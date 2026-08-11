"""Row construction and mutation bookkeeping."""
import store
from store import db


def new_row(fields, common=True):
    row = {"id": db.mint_id(), "created_at": store.now()}
    if common:
        row["updated_at"] = store.now()
        row["version"] = 1
    row.update(fields)
    return row


def touch(row):
    """PRD 2.4: `version` increases by exactly one on every mutation, and
    `updated_at` is refreshed to the logical clock's current instant."""
    row["updated_at"] = store.now()
    row["version"] = row["version"] + 1
    return row
