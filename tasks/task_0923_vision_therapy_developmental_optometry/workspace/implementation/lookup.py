"""Existence rungs 5-11 and the clinical write gate (rung 12)."""

from errors import ApiError
from store import db


# ------------------------------------------------- rungs 5..11, in order ---
def patient_or_404(patient_id):
    row = db.patients.get(patient_id)
    if row is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND")
    return row


def coverage_or_404(coverage_id):
    row = db.coverages.get(coverage_id)
    if row is None:
        raise ApiError("ERR_COVERAGE_NOT_FOUND")
    return row


def assessment_or_404(assessment_id):
    row = db.assessments.get(assessment_id)
    if row is None:
        raise ApiError("ERR_ASSESSMENT_NOT_FOUND")
    return row


def plan_or_404(plan_id):
    row = db.plans.get(plan_id)
    if row is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    return row


def session_or_404(session_id):
    row = db.sessions.get(session_id)
    if row is None:
        raise ApiError("ERR_SESSION_NOT_FOUND")
    return row


def claim_or_404(claim_id):
    row = db.claims.get(claim_id)
    if row is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND")
    return row


def reference_or_404(collection, row_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError("ERR_REFERENCE_NOT_FOUND")
    return row


def payer_or_404(payer_id):
    return reference_or_404(db.payers, payer_id)


def therapist_or_404(therapist_id):
    return reference_or_404(db.therapists, therapist_id)


def room_or_404(room_id):
    return reference_or_404(db.rooms, room_id)


def authorization_or_404(auth_id):
    return reference_or_404(db.authorizations, auth_id)


def phase_or_404(phase_id):
    return reference_or_404(db.phases, phase_id)


def kit_item_or_404(item_id):
    return reference_or_404(db.kit_items, item_id)


def kit_loan_or_404(loan_id):
    return reference_or_404(db.kit_loans, loan_id)


def referral_or_404(referral_id):
    return reference_or_404(db.referrals, referral_id)


def occlusion_or_404(presc_id):
    return reference_or_404(db.occlusions, presc_id)


# --------------------------------------- rung 12: clinical write gate -----
def discharge_gate(patient):
    """Rung 12.  Called only from the twenty-nine clinical-write endpoints
    enumerated in PRD §2.8; the sixteen non-gated writes and all twenty-four
    GETs never call it."""
    if patient is not None and patient.get("clinical_status") == "DISCHARGED":
        raise ApiError("ERR_PATIENT_DISCHARGED")


def gate_for_plan(plan):
    discharge_gate(db.patients.get(plan["patient_id"]))


def gate_for_patient_id(patient_id):
    discharge_gate(db.patients.get(patient_id))
