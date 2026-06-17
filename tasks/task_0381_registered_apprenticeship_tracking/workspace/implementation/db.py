"""In-memory data store.

The store starts EMPTY on every boot. No seeding. Every entity is created by
tests via the declared API surface.
"""
import itertools
import uuid

from response import now_iso

# Each collection: dict of id -> record (plain dict).
sponsors = {}
programs = {}
wage_steps = {}
milestones = {}
journeyworkers = {}
apprentices = {}
agreements = {}
ojt_entries = {}
rti_records = {}
milestone_attainments = {}
certificates = {}
eeo_reports = {}

# Monotonic sequence to provide a stable tiebreak for created_at ordering, since
# multiple records may share the same millisecond timestamp.
_seq = itertools.count()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def base_record(common_fields=True):
    """Create the system-managed scaffolding for a new record.

    common_fields=True  -> id, created_at, updated_at, version (=1)
    common_fields=False -> id, created_at only (immutable artifacts)
    """
    ts = now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if common_fields:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec, bump_version=True):
    """Refresh updated_at and (optionally) bump version on mutation."""
    rec["updated_at"] = now_iso()
    if bump_version and "version" in rec:
        rec["version"] += 1
