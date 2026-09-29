"""In-memory data store.  Starts completely empty on every boot — nothing is
seeded, preloaded or hardcoded (PRD entities are created only through the API).
"""
import itertools
import threading
import uuid

import clock

LOCK = threading.RLock()

_seq_counter = itertools.count(1)

# ---- collections ------------------------------------------------------------
professions = {}
reciprocal_agreements = {}
applicants = {}
credentials = {}
training_records = {}
disciplinary_records = {}
applications = {}
evaluations = {}
credit_awards = {}
permits = {}
licenses = {}
ledger_entries = {}
evaluators = {}
assignments = {}

_license_sequence = itertools.count(1)


def next_license_sequence():
    return next(_license_sequence)


def new_id():
    return str(uuid.uuid4())


def make_row(fields, audited=True):
    """Create a row with the standard identity/audit triplet (PRD §2.4)."""
    now = clock.now()
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = now
    if audited:
        row["updated_at"] = now
        row["version"] = 1
    row["_seq"] = next(_seq_counter)
    return row


def touch(row):
    """A mutation: refresh updated_at and increment version by exactly one."""
    row["updated_at"] = clock.now()
    row["version"] = row["version"] + 1
    return row


def order_key(row):
    """created_at ascending, with insertion order as a stable tie-break."""
    return (row["created_at"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=order_key)
