"""Existence checks and lookups, separated for testability."""
from __future__ import annotations

from typing import Any

from ..errors import err_not_found, err_reference_not_found
from ..store import store


def get_patient_or_404(patient_id: str) -> dict[str, Any]:
    row = store().patients.get(patient_id)
    if not row:
        raise err_not_found(f"Patient {patient_id} not found")
    return row


def get_therapist_or_404(therapist_id: str) -> dict[str, Any]:
    row = store().therapists.get(therapist_id)
    if not row:
        raise err_not_found(f"Therapist {therapist_id} not found")
    return row


def get_episode_or_404(episode_id: str) -> dict[str, Any]:
    row = store().episodes.get(episode_id)
    if not row:
        raise err_not_found(f"Episode {episode_id} not found")
    return row


def get_evaluation_or_404(evaluation_id: str) -> dict[str, Any]:
    row = store().evaluations.get(evaluation_id)
    if not row:
        raise err_not_found(f"Evaluation {evaluation_id} not found")
    return row


def get_poc_or_404(poc_id: str) -> dict[str, Any]:
    row = store().plan_of_cares.get(poc_id)
    if not row:
        raise err_not_found(f"PlanOfCare {poc_id} not found")
    return row


def get_authorization_or_404(authorization_id: str) -> dict[str, Any]:
    row = store().authorizations.get(authorization_id)
    if not row:
        raise err_not_found(f"Authorization {authorization_id} not found")
    return row


def get_visit_or_404(visit_id: str) -> dict[str, Any]:
    row = store().visits.get(visit_id)
    if not row:
        raise err_not_found(f"Visit {visit_id} not found")
    return row


def get_hep_or_404(hep_id: str) -> dict[str, Any]:
    row = store().home_exercise_programs.get(hep_id)
    if not row:
        raise err_not_found(f"HomeExerciseProgram {hep_id} not found")
    return row


def get_discharge_or_404(discharge_id: str) -> dict[str, Any]:
    row = store().discharge_assessments.get(discharge_id)
    if not row:
        raise err_not_found(f"DischargeAssessment {discharge_id} not found")
    return row


def get_veteran_referral_or_404(referral_id: str) -> dict[str, Any]:
    row = store().veteran_referrals.get(referral_id)
    if not row:
        raise err_not_found(f"VeteranReferral {referral_id} not found")
    return row


# ---- reference (body) checks -----------------------------------------------

def get_patient_ref(patient_id: str) -> dict[str, Any]:
    row = store().patients.get(patient_id)
    if not row:
        raise err_reference_not_found(f"Referenced patient {patient_id} does not exist")
    return row


def get_therapist_ref(therapist_id: str) -> dict[str, Any]:
    row = store().therapists.get(therapist_id)
    if not row:
        raise err_reference_not_found(f"Referenced therapist {therapist_id} does not exist")
    return row


def get_evaluation_ref(evaluation_id: str) -> dict[str, Any]:
    row = store().evaluations.get(evaluation_id)
    if not row:
        raise err_reference_not_found(f"Referenced evaluation {evaluation_id} does not exist")
    return row


def get_poc_ref(poc_id: str) -> dict[str, Any]:
    row = store().plan_of_cares.get(poc_id)
    if not row:
        raise err_reference_not_found(f"Referenced plan_of_care {poc_id} does not exist")
    return row


def get_authorization_ref(authorization_id: str) -> dict[str, Any]:
    row = store().authorizations.get(authorization_id)
    if not row:
        raise err_reference_not_found(f"Referenced authorization {authorization_id} does not exist")
    return row


def get_visit_ref(visit_id: str) -> dict[str, Any]:
    row = store().visits.get(visit_id)
    if not row:
        raise err_reference_not_found(f"Referenced visit {visit_id} does not exist")
    return row
