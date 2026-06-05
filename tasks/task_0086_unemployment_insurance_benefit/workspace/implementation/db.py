"""In-memory data store. Starts empty on every boot — no seeding.

Each entity collection is a dict keyed by the server-minted UUID id.
A monotonic sequence backs deterministic ordering when created_at ties.
"""
import itertools
import uuid

from clock import clock

# entity_type -> { id: record_dict }
employers = {}
claimants = {}
wage_records = {}
claims = {}
determinations = {}
weekly_certifications = {}
work_search_contacts = {}
employer_charges = {}
overpayments = {}
overpayment_recoveries = {}
appeals = {}
extension_programs = {}

_seq = itertools.count(1)


def reset():
    for coll in (employers, claimants, wage_records, claims, determinations,
                 weekly_certifications, work_search_contacts, employer_charges,
                 overpayments, overpayment_recoveries, appeals, extension_programs):
        coll.clear()


def new_id():
    return str(uuid.uuid4())


def _seqno():
    return next(_seq)


def stamp_create(record, with_version=True):
    """Attach common system fields on creation."""
    now = clock.now_iso()
    record["id"] = record.get("id") or new_id()
    record["created_at"] = now
    record["_seq"] = _seqno()
    if with_version:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and bump version (PRD §2.4)."""
    record["updated_at"] = clock.now_iso()
    record["version"] = record.get("version", 0) + 1
