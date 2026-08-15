"""In-memory data store (PRD 2.4 common fields, 2.7 logical-clock stamps).

The store starts EMPTY on every boot: no seeding, no preloading.  Every row a
test needs is built through the declared API surface.

Nine primary resources carry id/created_at/updated_at/version; ChecklistItem,
LaborEntry, and LogbookEntry carry only id/created_at.
"""

import itertools
import uuid

import clock as clockmod

OWNERS = {}
AIRCRAFT = {}
MECHANICS = {}
HANGAR_SLOTS = {}
WORK_ORDERS = {}
CHECKLIST_ITEMS = {}
DISCREPANCIES = {}
DIRECTIVES = {}
PARTS = {}
LABOR_ENTRIES = {}
LOGBOOK_ENTRIES = {}
INVOICES = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def stamp_new(record, versioned=True):
    record["id"] = new_id()
    record["created_at"] = clockmod.now_iso()
    record["_seq"] = next(_seq)
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and increment version on a mutated row (PRD 2.4)."""
    record["updated_at"] = clockmod.now_iso()
    record["version"] += 1
    return record


def sort_rows(rows):
    """List endpoints sort by created_at ascending (PRD 2.3); _seq breaks ties."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
