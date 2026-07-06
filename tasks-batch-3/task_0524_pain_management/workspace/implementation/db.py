import itertools
import uuid

import util

# In-memory stores keyed by id. Every store starts empty on process boot.
# NO seeding / preloading of any entity data.
clinics = {}
providers = {}
patients = {}
opioid_agreements = {}
pdmp_checks = {}
treatment_plans = {}
fluoroscopy_suites = {}
procedures = {}
prior_authorizations = {}
prescriptions = {}
urine_drug_screens = {}
pill_count_audits = {}
ledgers = {}  # ControlledSubstanceLedger, keyed by ledger id

# Secondary index: patient_id -> ledger id
ledger_by_patient = {}

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# Deterministic per-entity creation sequence so created_at ties break in
# creation order for sorting (timestamps can collide within a test).
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def base_fields(with_version=True, clock=None):
    """Build the common system fields.

    created_at / updated_at are stamped from the clinic's logical clock when a
    `clock` (ISO string) is supplied, so that time-window calculations
    (elapsed days, expiry, freshness) that compare created_at against
    clinic.current_utc are deterministic under the test-driven logical clock.
    Entities with no clinic context (the Clinic itself) fall back to now().
    """
    ts = clock if clock is not None else util.now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next(_seq),
    }
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec, clock=None):
    """Mutation bump: refresh updated_at and increment version."""
    rec["updated_at"] = clock if clock is not None else util.now_iso()
    rec["version"] = rec.get("version", 1) + 1
