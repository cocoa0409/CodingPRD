"""In-memory data store. All state is process-local and starts empty on boot.

NO seeding: every entity is created via the API. Per-test-server isolation
wipes the process (and therefore this module's dicts) before every test.
"""
import itertools
import uuid

from response import now_iso

# One dict per entity collection, keyed by id.
employers = {}
wage_rulesets = {}
worksites = {}
employees = {}
shifts = {}
punches = {}
time_edits = {}
break_records = {}
tip_declarations = {}
tip_pools = {}
timesheet_weeks = {}
payroll_runs = {}

# Monotonic counter used to preserve stable insertion order for tie-breaks
# and created_at-ascending sorts (timestamps can collide at ms granularity).
_seq = itertools.count(1)


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def base_fields():
    """Common system fields: id, created_at, updated_at, version (PRD §2.4).

    version starts at 1 on creation and increments by one on every mutation.
    `_seq` is an internal insertion-order key (never serialized).
    """
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_seq),
    }


def touch(record):
    """Mutation bookkeeping: bump updated_at and version (PRD §2.4)."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
