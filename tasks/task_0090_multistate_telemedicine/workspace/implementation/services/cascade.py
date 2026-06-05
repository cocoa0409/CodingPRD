"""StateLicense suspension cascade (SCAFFOLD §1.2 / PRD §3.4 / §2.8).

Chain (license -> visit -> prescription, with claim reversal hanging off the
insurance visit's void):

  License SUSPENDED
    -> every Visit in {COMPLIANCE_CLEARED, APPROVED_INSURANCE, APPROVED_SELF_PAY}
       whose clearing ComplianceCheck.matched_license_id == suspended license  -> VOIDED
         -> every Prescription on that visit with status ACTIVE                 -> VOIDED
         -> (APPROVED_INSURANCE only) every Claim on that visit in
            {SUBMITTED, ADJUDICATED}                                            -> REVERSED

Each affected resource is independently mutated: updated_at refreshed + version
incremented (PRD §2.8). ComplianceChecks are append-only and not re-touched.
"""
import db
from . import store

VOIDABLE_VISIT_STATUSES = {"COMPLIANCE_CLEARED", "APPROVED_INSURANCE", "APPROVED_SELF_PAY"}


def _clearing_license_id(visit_id):
    """The matched_license_id from the most recent CLEARED/OVERRIDDEN check that
    governs this visit. The visit was cleared by run-compliance (CLEARED, with a
    matched_license_id) or override (OVERRIDDEN, matched_license_id null). Only
    CLEARED checks carry a license id, so we look for the governing license among
    this visit's compliance checks.
    """
    checks = [c for c in db.compliance_checks.values() if c["visit_id"] == visit_id]
    # The governing license is the matched_license_id of the CLEARED check.
    cleared = [c for c in checks if c["outcome"] == "CLEARED" and c.get("matched_license_id")]
    if not cleared:
        return None
    # most recent by created_at, tie-break by append sequence (same logical-clock
    # instant must not be ordered by random UUID id)
    cleared.sort(key=lambda c: (db.parse_iso(c["created_at"]).timestamp(), c.get("_seq", 0)))
    return cleared[-1]["matched_license_id"]


def void_prescriptions_for_visit(visit_id):
    for p in db.prescriptions.values():
        if p["visit_id"] == visit_id and p["status"] == "ACTIVE":
            p["status"] = "VOIDED"
            store.touch(p)


def reverse_claims_for_visit(visit_id):
    for c in db.claims.values():
        if c["visit_id"] == visit_id and c["status"] in ("SUBMITTED", "ADJUDICATED"):
            c["status"] = "REVERSED"
            store.touch(c)


def suspend_cascade(license_id):
    """Run the full cascade for a license being suspended."""
    for v in db.visits.values():
        if v["status"] not in VOIDABLE_VISIT_STATUSES:
            continue
        if _clearing_license_id(v["id"]) != license_id:
            continue
        was_insurance = v["status"] == "APPROVED_INSURANCE"
        # First hop: visit -> VOIDED
        v["status"] = "VOIDED"
        store.touch(v)
        # Second hop: prescriptions -> VOIDED
        void_prescriptions_for_visit(v["id"])
        # Third hop (insurance only): claims -> REVERSED
        if was_insurance:
            reverse_claims_for_visit(v["id"])
