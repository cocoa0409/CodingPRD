"""Payload factories — one per writeable entity. Only PRD §3-declared input fields.

All factories accept **overrides so tests can pin specific fields when their
assertions depend on a particular value (e.g., dates, minutes, codes).
"""
import uuid

from .constants import DEFAULT_DIAGNOSIS_ICD10, DEFAULT_LICENSE_STATE


# ─── Counter to keep unique values across a single test run ──────


_npi_counter = [9000000000]


def _next_npi() -> str:
    """A 10-digit NPI number unique within a test run (PRD §3.1)."""
    _npi_counter[0] += 1
    return str(_npi_counter[0])


_referral_counter = [0]


def _next_referral_auth_number() -> str:
    """A unique referral_authorization_number (PRD §3.2)."""
    _referral_counter[0] += 1
    return f"VA-AUTH-{_referral_counter[0]:08d}"


# ─── Patient (PRD §3.1) ─────────────────────────────────────────


def create_patient_payload(
    full_name: str = "Test Patient",
    date_of_birth: str = "1970-01-01",
    insurance_type: str = "COMMERCIAL",
    is_veteran: bool = False,
    **overrides,
) -> dict:
    payload = {
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "insurance_type": insurance_type,
        "is_veteran": is_veteran,
    }
    payload.update(overrides)
    return payload


# ─── Therapist (PRD §3.1) ───────────────────────────────────────


def create_therapist_payload(
    full_name: str = "Test Therapist",
    npi_number: str = None,
    license_state: str = DEFAULT_LICENSE_STATE,
    medicare_provider_enrolled: bool = False,
    **overrides,
) -> dict:
    payload = {
        "full_name": full_name,
        "npi_number": npi_number if npi_number is not None else _next_npi(),
        "license_state": license_state,
        "medicare_provider_enrolled": medicare_provider_enrolled,
    }
    payload.update(overrides)
    return payload


# ─── VeteranReferral (PRD §3.2) ─────────────────────────────────


def create_veteran_referral_payload(
    patient_id: str,
    referring_va_facility_code: str = "VA001",
    referral_authorization_number: str = None,
    max_authorized_visits: int = 20,
    expires_on: str = "2026-12-31",
    **overrides,
) -> dict:
    payload = {
        "patient_id": patient_id,
        "referring_va_facility_code": referring_va_facility_code,
        "referral_authorization_number": (
            referral_authorization_number
            if referral_authorization_number is not None
            else _next_referral_auth_number()
        ),
        "max_authorized_visits": max_authorized_visits,
        "expires_on": expires_on,
    }
    payload.update(overrides)
    return payload


# ─── PlanOfCare (PRD §3.2, §3.6) ────────────────────────────────


def create_plan_of_care_payload(
    patient_id: str,
    primary_therapist_id: str,
    diagnosis_icd10: str = DEFAULT_DIAGNOSIS_ICD10,
    certified_start_date: str = "2026-06-01",
    certified_end_date: str = "2026-07-31",
    veteran_referral_id: str = None,
    **overrides,
) -> dict:
    payload = {
        "patient_id": patient_id,
        "primary_therapist_id": primary_therapist_id,
        "diagnosis_icd10": diagnosis_icd10,
        "certified_start_date": certified_start_date,
        "certified_end_date": certified_end_date,
    }
    if veteran_referral_id is not None:
        payload["veteran_referral_id"] = veteran_referral_id
    payload.update(overrides)
    return payload


def recertify_plan_payload(
    expected_plan_of_care_version: int,
    certified_start_date: str,
    certified_end_date: str,
    **overrides,
) -> dict:
    payload = {
        "expected_plan_of_care_version": expected_plan_of_care_version,
        "certified_start_date": certified_start_date,
        "certified_end_date": certified_end_date,
    }
    payload.update(overrides)
    return payload


# ─── Evaluation (PRD §3.3) ──────────────────────────────────────


def create_evaluation_payload(
    plan_of_care_id: str,
    therapist_id: str,
    evaluation_kind: str = "INITIAL",
    performed_on: str = "2026-06-01",
    functional_score: int = 40,
    minutes_spent: int = 30,
    **overrides,
) -> dict:
    payload = {
        "plan_of_care_id": plan_of_care_id,
        "therapist_id": therapist_id,
        "evaluation_kind": evaluation_kind,
        "performed_on": performed_on,
        "functional_score": functional_score,
        "minutes_spent": minutes_spent,
    }
    payload.update(overrides)
    return payload


# ─── AuthorizationGrant (PRD §3.4) ──────────────────────────────


def create_authorization_grant_payload(
    plan_of_care_id: str,
    total_units_granted: int = 20,
    effective_from: str = "2026-06-01",
    effective_to: str = "2026-07-31",
    veteran_referral_id: str = None,
    **overrides,
) -> dict:
    payload = {
        "plan_of_care_id": plan_of_care_id,
        "total_units_granted": total_units_granted,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    if veteran_referral_id is not None:
        payload["veteran_referral_id"] = veteran_referral_id
    payload.update(overrides)
    return payload


# ─── Visit (PRD §3.5) ───────────────────────────────────────────


def create_visit_payload(
    authorization_grant_id: str,
    therapist_id: str,
    scheduled_start_utc: str = "2026-06-02T09:00:00Z",
    scheduled_end_utc: str = "2026-06-02T09:30:00Z",
    planned_minutes: int = 30,
    cpt_code: str = "CPT_97110_THER_EX",
    **overrides,
) -> dict:
    payload = {
        "authorization_grant_id": authorization_grant_id,
        "therapist_id": therapist_id,
        "scheduled_start_utc": scheduled_start_utc,
        "scheduled_end_utc": scheduled_end_utc,
        "planned_minutes": planned_minutes,
        "cpt_code": cpt_code,
    }
    payload.update(overrides)
    return payload


def complete_visit_payload(actual_minutes: int = 30, **overrides) -> dict:
    payload = {"actual_minutes": actual_minutes}
    payload.update(overrides)
    return payload


def finalize_visit_payload(expected_plan_of_care_version: int, **overrides) -> dict:
    payload = {"expected_plan_of_care_version": expected_plan_of_care_version}
    payload.update(overrides)
    return payload


# ─── HomeExerciseProgram (PRD §3.7) ─────────────────────────────


def create_home_exercise_program_payload(
    plan_of_care_id: str,
    prescribed_by_therapist_id: str,
    exercise_count: int = 5,
    weekly_frequency: int = 3,
    prescribed_on: str = "2026-06-02",
    **overrides,
) -> dict:
    payload = {
        "plan_of_care_id": plan_of_care_id,
        "prescribed_by_therapist_id": prescribed_by_therapist_id,
        "exercise_count": exercise_count,
        "weekly_frequency": weekly_frequency,
        "prescribed_on": prescribed_on,
    }
    payload.update(overrides)
    return payload


# ─── MIPSQualityMeasure (PRD §3.7) ──────────────────────────────


def create_mips_measure_payload(
    patient_id: str,
    plan_of_care_id: str,
    reporting_therapist_id: str,
    measure_code: str = "MIPS128_FALL_RISK",
    performance_period_start: str = "2026-06-01",
    performance_period_end: str = "2026-06-30",
    numerator_met: bool = True,
    **overrides,
) -> dict:
    payload = {
        "patient_id": patient_id,
        "plan_of_care_id": plan_of_care_id,
        "reporting_therapist_id": reporting_therapist_id,
        "measure_code": measure_code,
        "performance_period_start": performance_period_start,
        "performance_period_end": performance_period_end,
        "numerator_met": numerator_met,
    }
    payload.update(overrides)
    return payload


def revise_mips_payload(**overrides) -> dict:
    """numerator_met and/or measure_code are the only revisable fields (PRD §3.7)."""
    payload = {}
    payload.update(overrides)
    return payload


# ─── DischargeAssessment (PRD §3.8) ─────────────────────────────


def create_discharge_assessment_payload(
    plan_of_care_id: str,
    assessing_therapist_id: str,
    final_functional_score: int = 70,
    goals_met_count: int = 8,
    total_goals_count: int = 10,
    assessed_on: str = "2026-06-10",
    **overrides,
) -> dict:
    payload = {
        "plan_of_care_id": plan_of_care_id,
        "assessing_therapist_id": assessing_therapist_id,
        "final_functional_score": final_functional_score,
        "goals_met_count": goals_met_count,
        "total_goals_count": total_goals_count,
        "assessed_on": assessed_on,
    }
    payload.update(overrides)
    return payload


# ─── Clock (PRD §2.10) ──────────────────────────────────────────


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
