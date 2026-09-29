"""In-memory data store.

Every collection starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded — tests build all preconditions through the declared API surface.
"""

import uuid

import clock

reporting_entities = {}
plants = {}
registrations = {}
reporting_windows = {}
submissions = {}
transaction_records = {}
wholesale_lots = {}
market_reports = {}
audit_cases = {}
penalty_assessments = {}
methodology_changes = {}
public_comments = {}

_seq = 0


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def insert(collection, data, versioned=True):
    """Insert a record, minting id / created_at (and updated_at / version)."""
    rec = dict(data)
    rec["id"] = new_id()
    rec["created_at"] = clock.iso_now()
    rec["_seq"] = _next_seq()
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    collection[rec["id"]] = rec
    return rec


def touch(rec):
    """Record a mutation: refresh updated_at from the logical clock, bump version."""
    rec["updated_at"] = clock.iso_now()
    rec["version"] = int(rec.get("version", 0)) + 1
    return rec


def ordered(records):
    """PRD §2.3 — results are always ordered by created_at ascending."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def reset():
    """Drop every record (used only by the process boot path / tests)."""
    for coll in (
        reporting_entities,
        plants,
        registrations,
        reporting_windows,
        submissions,
        transaction_records,
        wholesale_lots,
        market_reports,
        audit_cases,
        penalty_assessments,
        methodology_changes,
        public_comments,
    ):
        coll.clear()
    global _seq
    _seq = 0
