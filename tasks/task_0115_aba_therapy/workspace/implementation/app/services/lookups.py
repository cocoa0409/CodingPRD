"""Resource lookup helpers — each raises ERR_NOT_FOUND when missing.

PRD §2.7: path parameters are validated strictly left-to-right; the first
missing segment causes ERR_NOT_FOUND (HTTP 404). Foreign-key body fields
are validated AFTER the full path is resolved.
"""
from typing import Dict

from ..errors import APIError
from ..store import get_store


def _get_or_404(table: Dict[str, dict], rid: str, label: str) -> dict:
    if not isinstance(rid, str) or not rid:
        raise APIError("ERR_NOT_FOUND", f"{label} not found")
    rec = table.get(rid)
    if rec is None:
        raise APIError("ERR_NOT_FOUND", f"{label} {rid} not found")
    return rec


def get_clinic(clinic_id: str) -> dict:
    return _get_or_404(get_store().clinics, clinic_id, "Clinic")


def get_patient(patient_id: str) -> dict:
    return _get_or_404(get_store().patients, patient_id, "Patient")


def get_therapist(therapist_id: str) -> dict:
    return _get_or_404(get_store().therapists, therapist_id, "Therapist")


def get_evaluation(evaluation_id: str) -> dict:
    return _get_or_404(get_store().evaluations, evaluation_id, "Evaluation")


def get_treatment_plan(plan_id: str) -> dict:
    return _get_or_404(get_store().treatment_plans, plan_id, "TreatmentPlan")


def get_authorization(authorization_id: str) -> dict:
    return _get_or_404(get_store().authorizations, authorization_id, "Authorization")


def get_session(session_id: str) -> dict:
    return _get_or_404(get_store().sessions, session_id, "TherapySession")


def get_claim(claim_id: str) -> dict:
    return _get_or_404(get_store().claims, claim_id, "InsuranceClaim")


def clinic_now(clinic_id: str) -> str:
    return get_clinic(clinic_id)["now_ts"]
