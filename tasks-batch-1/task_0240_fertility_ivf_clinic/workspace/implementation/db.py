"""In-memory data store. Starts empty on every boot; no seeding.

Each collection is a dict keyed by entity id. A monotonically increasing
sequence backs the insertion-order / created_at sort (PRD §2.3).
"""

import itertools
import uuid

from response import now_iso

# Per-collection id -> record dicts.
clinics = {}
packages = {}
patients = {}
donors = {}
surrogates = {}
consent_forms = {}
patient_consents = {}
tanks = {}
cycles = {}
medications = {}
appointments = {}
specimens = {}
invoices = {}
outcomes = {}

# Global insertion sequence so list ordering by creation is stable even when
# timestamps collide (multiple records minted in the same millisecond).
_seq = itertools.count(1)


def reset():
    for d in (
        clinics, packages, patients, donors, surrogates, consent_forms,
        patient_consents, tanks, cycles, medications, appointments,
        specimens, invoices, outcomes,
    ):
        d.clear()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def new_record(extra=None, versioned=True):
    """Create a base record with id/created_at/(updated_at/version) common fields."""
    rec = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": next_seq(),
    }
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    if extra:
        rec.update(extra)
    return rec


def touch(rec):
    """A mutation: refresh updated_at and bump version (PRD §2.4)."""
    rec["updated_at"] = now_iso()
    if "version" in rec:
        rec["version"] += 1
