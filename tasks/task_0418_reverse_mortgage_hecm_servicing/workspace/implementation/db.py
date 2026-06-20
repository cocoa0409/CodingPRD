"""In-memory data store. Starts EMPTY on every boot; no seeding."""
import itertools
import uuid

from response import now_iso

# One dict per entity collection, keyed by id.
lenders = {}
principal_limit_factors = {}
borrowers = {}
loans = {}
disbursements = {}
lesa_set_asides = {}
property_charge_payments = {}
occupancy_certifications = {}
maturity_events = {}
nbs_deferrals = {}
resolutions = {}
ledger_entries = {}

# Monotonic creation sequence so created_at ties sort deterministically by
# insertion order (created_at ascending). Timestamps may collide at ms.
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def stamp_create(record, with_version=True):
    """Attach common create fields. with_version=False for lean entities
    (PrincipalLimitFactor, LedgerEntry) which carry only id + created_at."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = next_seq()
    if with_version:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Mark a mutation: bump updated_at + version by 1."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
