"""Entity assertions and domain invariant checkers.

Each per-entity assert_<entity>() verifies the PRD-declared shape of a
single response payload. Field names mirror PRD prose exactly.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Status value sets — verbatim from PRD entity descriptions.
# ---------------------------------------------------------------------------
PATIENT_STATUSES = {"ACTIVE", "ARCHIVED"}
INSURANCE_TYPES = {"MEDICARE_PART_B", "VA", "COMMERCIAL", "SELF_PAY"}
THERAPIST_CREDENTIALS = {"PT", "PTA", "DPT"}
THERAPIST_STATUSES = {"ACTIVE", "INACTIVE"}
EPISODE_STATUSES = {
    "DRAFT", "EVALUATED", "ACTIVE", "REEVAL_DUE",
    "DISCHARGE_PENDING", "DISCHARGED", "CANCELLED",
}
BODY_REGIONS = {
    "LUMBAR", "CERVICAL", "KNEE", "SHOULDER", "HIP", "ANKLE", "OTHER",
}
CAP_POLICIES = {"CAPPED", "UNCAPPED"}
DISCHARGE_OUTCOMES = {
    "GOALS_MET", "PARTIAL", "PLATEAU", "ADVERSE_EVENT", "PATIENT_WITHDREW",
}
EVALUATION_STATUSES = {"DRAFT", "FINALIZED", "AMENDED"}
EVALUATION_TYPES = {"INITIAL", "REEVAL"}
EVALUATION_COMPLEXITIES = {"LOW", "MODERATE", "HIGH"}
PLAN_OF_CARE_STATUSES = {
    "DRAFT", "CERTIFIED", "ACTIVE", "EXPIRED", "REVOKED",
}
AUTHORIZATION_STATUSES = {"APPROVED", "EXPIRED", "REVOKED"}
AUTHORIZATION_SOURCES = {
    "COMMERCIAL_PAYER", "MEDICARE_AUTO", "VA_REFERRAL",
}
VISIT_STATUSES = {
    "SCHEDULED", "IN_SESSION", "SIGNED", "BILLED", "CANCELLED",
}
HEP_STATUSES = {"DRAFT", "ISSUED", "ACKNOWLEDGED", "SUPERSEDED"}
DISCHARGE_ASSESSMENT_STATUSES = {"DRAFT", "SIGNED"}
MIPS_MEASURE_CODES = {
    "Q126_PAIN_ASSESSMENT",
    "Q127_FUNCTIONAL_STATUS",
    "Q128_FALL_RISK_SCREEN",
}
MIPS_EXCEPTION_REASONS = {"NONE", "MEDICAL", "PATIENT", "SYSTEM"}
VETERAN_REFERRAL_STATUSES = {"ACTIVE", "CONSUMED", "EXPIRED"}


# ---------------------------------------------------------------------------
# Common-fields helpers — PRD §2.4.
# ---------------------------------------------------------------------------
def _assert_common_fields(data: Dict[str, Any], entity_name: str) -> None:
    """PRD §2.4: id (UUID), created_at, updated_at (ISO 8601), version
    integer >= 1."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity_name}.version must be an integer"
    )
    assert data["version"] >= 1, (
        f"{entity_name}.version must be >= 1"
    )


def _assert_appendonly_fields(data: Dict[str, Any],
                              entity_name: str) -> None:
    """PRD §2.4: append-only entities carry only id + created_at; no
    updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )


# ---------------------------------------------------------------------------
# Patient — PRD §3.1.
# ---------------------------------------------------------------------------
def assert_patient(data: Dict[str, Any]) -> None:
    """PRD §3.1 / §2.4."""
    _assert_common_fields(data, "Patient")
    assert isinstance(data.get("full_name"), str) and data["full_name"], (
        "Patient.full_name must be a non-empty string"
    )
    assert isinstance(data.get("date_of_birth"), str), (
        "Patient.date_of_birth must be an ISO date string"
    )
    assert data.get("insurance_type") in INSURANCE_TYPES, (
        f"Patient.insurance_type must be one of {INSURANCE_TYPES}, "
        f"got {data.get('insurance_type')!r}"
    )
    assert data.get("status") in PATIENT_STATUSES, (
        f"Patient.status must be one of {PATIENT_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    assert isinstance(data.get("ytd_capped_amount_cents"), int), (
        "Patient.ytd_capped_amount_cents must be an integer"
    )
    assert data["ytd_capped_amount_cents"] >= 0, (
        "Patient.ytd_capped_amount_cents must be >= 0"
    )


# ---------------------------------------------------------------------------
# Therapist — PRD §3.1.
# ---------------------------------------------------------------------------
def assert_therapist(data: Dict[str, Any]) -> None:
    """PRD §3.1 / §2.4."""
    _assert_common_fields(data, "Therapist")
    assert isinstance(data.get("full_name"), str) and data["full_name"], (
        "Therapist.full_name must be a non-empty string"
    )
    assert isinstance(data.get("npi"), str) and data["npi"], (
        "Therapist.npi must be a non-empty string"
    )
    assert data.get("credential") in THERAPIST_CREDENTIALS, (
        f"Therapist.credential must be one of {THERAPIST_CREDENTIALS}, "
        f"got {data.get('credential')!r}"
    )
    # PRD §3.1: "can_evaluate automatically: it is true when the
    # credential is PT or DPT, and false when the credential is PTA."
    assert isinstance(data.get("can_evaluate"), bool), (
        "Therapist.can_evaluate must be a boolean"
    )
    if data["credential"] in {"PT", "DPT"}:
        assert data["can_evaluate"] is True, (
            "Therapist.can_evaluate must be true for PT/DPT credential"
        )
    elif data["credential"] == "PTA":
        assert data["can_evaluate"] is False, (
            "Therapist.can_evaluate must be false for PTA credential"
        )
    assert data.get("status") in THERAPIST_STATUSES, (
        f"Therapist.status must be one of {THERAPIST_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Episode — PRD §3.2.
# ---------------------------------------------------------------------------
def assert_episode(data: Dict[str, Any]) -> None:
    """PRD §3.2 / §2.4."""
    _assert_common_fields(data, "Episode")
    assert is_valid_uuid(data.get("patient_id", "")), (
        "Episode.patient_id must be a UUID"
    )
    assert isinstance(data.get("referring_provider_npi"), str), (
        "Episode.referring_provider_npi must be a string"
    )
    assert data.get("body_region") in BODY_REGIONS, (
        f"Episode.body_region must be one of {BODY_REGIONS}, "
        f"got {data.get('body_region')!r}"
    )
    assert data.get("status") in EPISODE_STATUSES, (
        f"Episode.status must be one of {EPISODE_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    # PRD §3.2: cap_policy is unset (null) until first evaluation
    # finalization stamps it.
    cap_policy = data.get("cap_policy")
    if cap_policy is not None:
        assert cap_policy in CAP_POLICIES, (
            f"Episode.cap_policy must be one of {CAP_POLICIES} or null, "
            f"got {cap_policy!r}"
        )
    assert isinstance(data.get("kx_modifier_required"), bool), (
        "Episode.kx_modifier_required must be a boolean"
    )
    # PRD §2.7: roll-up counters.
    for fld in ("total_authorized_units", "total_committed_units",
                "total_reserved_units"):
        assert isinstance(data.get(fld), int), (
            f"Episode.{fld} must be an integer"
        )
        assert data[fld] >= 0, f"Episode.{fld} must be >= 0"


def assert_episode_unit_invariant(data: Dict[str, Any]) -> None:
    """PRD §2.7: "reserved units plus committed units never exceed
    authorized units"."""
    reserved = data["total_reserved_units"]
    committed = data["total_committed_units"]
    authorized = data["total_authorized_units"]
    assert reserved + committed <= authorized, (
        f"Unit invariant breached: reserved={reserved} + "
        f"committed={committed} > authorized={authorized}"
    )


# ---------------------------------------------------------------------------
# Evaluation — PRD §3.2.
# ---------------------------------------------------------------------------
def assert_evaluation(data: Dict[str, Any]) -> None:
    """PRD §3.2 / §2.4."""
    _assert_common_fields(data, "Evaluation")
    assert is_valid_uuid(data.get("episode_id", "")), (
        "Evaluation.episode_id must be a UUID"
    )
    assert data.get("evaluation_type") in EVALUATION_TYPES, (
        f"Evaluation.evaluation_type must be one of {EVALUATION_TYPES}"
    )
    assert is_valid_uuid(data.get("clinician_id", "")), (
        "Evaluation.clinician_id must be a UUID"
    )
    assert data.get("complexity") in EVALUATION_COMPLEXITIES, (
        f"Evaluation.complexity must be one of "
        f"{EVALUATION_COMPLEXITIES}"
    )
    assert isinstance(data.get("functional_baseline_score"), int), (
        "Evaluation.functional_baseline_score must be an integer"
    )
    assert data.get("status") in EVALUATION_STATUSES, (
        f"Evaluation.status must be one of {EVALUATION_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    finalized_at = data.get("finalized_at")
    if data["status"] in {"FINALIZED", "AMENDED"}:
        assert is_iso8601_timestamp(finalized_at or ""), (
            "Evaluation.finalized_at must be ISO 8601 in "
            "FINALIZED/AMENDED"
        )


# ---------------------------------------------------------------------------
# PlanOfCare — PRD §3.3.
# ---------------------------------------------------------------------------
def assert_plan_of_care(data: Dict[str, Any]) -> None:
    """PRD §3.3 / §2.4."""
    _assert_common_fields(data, "PlanOfCare")
    assert is_valid_uuid(data.get("episode_id", "")), (
        "PlanOfCare.episode_id must be a UUID"
    )
    assert is_valid_uuid(data.get("evaluation_id", "")), (
        "PlanOfCare.evaluation_id must be a UUID"
    )
    assert isinstance(data.get("certifying_physician_npi"), str), (
        "PlanOfCare.certifying_physician_npi must be a string"
    )
    assert isinstance(data.get("planned_visit_count"), int), (
        "PlanOfCare.planned_visit_count must be an integer"
    )
    assert isinstance(data.get("planned_units_per_visit"), int), (
        "PlanOfCare.planned_units_per_visit must be an integer"
    )
    assert isinstance(data.get("cert_period_start"), str), (
        "PlanOfCare.cert_period_start must be an ISO date string"
    )
    assert isinstance(data.get("cert_period_end"), str), (
        "PlanOfCare.cert_period_end must be an ISO date string"
    )
    assert data.get("status") in PLAN_OF_CARE_STATUSES, (
        f"PlanOfCare.status must be one of {PLAN_OF_CARE_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Authorization — PRD §3.4. Append-only per PRD §2.4 (no updated_at /
# version are listed in §2.4 for Authorization, but only MipsMeasure and
# VeteranReferral are explicitly named there. To stay conservative we
# only assert id + created_at and known fields).
# ---------------------------------------------------------------------------
def assert_authorization(data: Dict[str, Any]) -> None:
    """PRD §3.4."""
    assert is_valid_uuid(data.get("id", "")), (
        f"Authorization.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "Authorization.created_at must be ISO 8601"
    )
    assert is_valid_uuid(data.get("episode_id", "")), (
        "Authorization.episode_id must be a UUID"
    )
    assert is_valid_uuid(data.get("plan_of_care_id", "")), (
        "Authorization.plan_of_care_id must be a UUID"
    )
    assert data.get("source") in AUTHORIZATION_SOURCES, (
        f"Authorization.source must be one of {AUTHORIZATION_SOURCES}, "
        f"got {data.get('source')!r}"
    )
    assert isinstance(data.get("external_reference"), str), (
        "Authorization.external_reference must be a string"
    )
    assert isinstance(data.get("unit_quota"), int), (
        "Authorization.unit_quota must be an integer"
    )
    assert isinstance(data.get("valid_from"), str), (
        "Authorization.valid_from must be a date/timestamp string"
    )
    assert isinstance(data.get("valid_through"), str), (
        "Authorization.valid_through must be a date/timestamp string"
    )
    assert data.get("status") in AUTHORIZATION_STATUSES, (
        f"Authorization.status must be one of "
        f"{AUTHORIZATION_STATUSES}, got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Visit — PRD §3.5.
# ---------------------------------------------------------------------------
def assert_visit(data: Dict[str, Any]) -> None:
    """PRD §3.5 / §2.4."""
    _assert_common_fields(data, "Visit")
    assert is_valid_uuid(data.get("episode_id", "")), (
        "Visit.episode_id must be a UUID"
    )
    assert is_valid_uuid(data.get("plan_of_care_id", "")), (
        "Visit.plan_of_care_id must be a UUID"
    )
    assert is_valid_uuid(data.get("authorization_id", "")), (
        "Visit.authorization_id must be a UUID"
    )
    assert is_valid_uuid(data.get("clinician_id", "")), (
        "Visit.clinician_id must be a UUID"
    )
    assert is_iso8601_timestamp(data.get("scheduled_start", "")), (
        "Visit.scheduled_start must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("scheduled_end", "")), (
        "Visit.scheduled_end must be ISO 8601"
    )
    assert isinstance(data.get("units_planned"), int), (
        "Visit.units_planned must be an integer"
    )
    assert isinstance(data.get("units_billed"), int), (
        "Visit.units_billed must be an integer"
    )
    assert isinstance(data.get("charge_cents"), int), (
        "Visit.charge_cents must be an integer"
    )
    assert isinstance(data.get("kx_applied"), bool), (
        "Visit.kx_applied must be a boolean"
    )
    assert data.get("status") in VISIT_STATUSES, (
        f"Visit.status must be one of {VISIT_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# HomeExerciseProgram — PRD §3.7.
# ---------------------------------------------------------------------------
def assert_home_exercise_program(data: Dict[str, Any]) -> None:
    """PRD §3.7 / §2.4."""
    _assert_common_fields(data, "HomeExerciseProgram")
    assert is_valid_uuid(data.get("episode_id", "")), (
        "HomeExerciseProgram.episode_id must be a UUID"
    )
    assert is_valid_uuid(data.get("plan_of_care_id", "")), (
        "HomeExerciseProgram.plan_of_care_id must be a UUID"
    )
    assert is_valid_uuid(data.get("prescribing_clinician_id", "")), (
        "HomeExerciseProgram.prescribing_clinician_id must be a UUID"
    )
    assert isinstance(data.get("exercise_items"), list), (
        "HomeExerciseProgram.exercise_items must be a list"
    )
    assert data.get("status") in HEP_STATUSES, (
        f"HomeExerciseProgram.status must be one of {HEP_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# DischargeAssessment — PRD §3.9.
# ---------------------------------------------------------------------------
def assert_discharge_assessment(data: Dict[str, Any]) -> None:
    """PRD §3.9 / §2.4."""
    _assert_common_fields(data, "DischargeAssessment")
    assert is_valid_uuid(data.get("episode_id", "")), (
        "DischargeAssessment.episode_id must be a UUID"
    )
    assert is_valid_uuid(data.get("discharging_clinician_id", "")), (
        "DischargeAssessment.discharging_clinician_id must be a UUID"
    )
    assert data.get("discharge_outcome") in DISCHARGE_OUTCOMES, (
        f"DischargeAssessment.discharge_outcome must be one of "
        f"{DISCHARGE_OUTCOMES}, got {data.get('discharge_outcome')!r}"
    )
    assert isinstance(data.get("final_functional_score"), int), (
        "DischargeAssessment.final_functional_score must be an integer"
    )
    assert data.get("status") in DISCHARGE_ASSESSMENT_STATUSES, (
        f"DischargeAssessment.status must be one of "
        f"{DISCHARGE_ASSESSMENT_STATUSES}, got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# MipsMeasure — append-only per PRD §2.4.
# ---------------------------------------------------------------------------
def assert_mips_measure(data: Dict[str, Any]) -> None:
    """PRD §3.8 / §2.4: MipsMeasure carries only id and created_at —
    no updated_at, no version."""
    _assert_appendonly_fields(data, "MipsMeasure")
    assert is_valid_uuid(data.get("episode_id", "")), (
        "MipsMeasure.episode_id must be a UUID"
    )
    assert data.get("measure_code") in MIPS_MEASURE_CODES, (
        f"MipsMeasure.measure_code must be one of {MIPS_MEASURE_CODES}, "
        f"got {data.get('measure_code')!r}"
    )
    assert is_valid_uuid(data.get("visit_id", "")), (
        "MipsMeasure.visit_id must be a UUID"
    )
    assert isinstance(data.get("numerator_met"), bool), (
        "MipsMeasure.numerator_met must be a boolean"
    )
    assert data.get("exception_reason") in MIPS_EXCEPTION_REASONS, (
        f"MipsMeasure.exception_reason must be one of "
        f"{MIPS_EXCEPTION_REASONS}, got {data.get('exception_reason')!r}"
    )
    # PRD §3.8: "The scored_at timestamp is set by the server when the
    # row is created."
    assert is_iso8601_timestamp(data.get("scored_at", "")), (
        "MipsMeasure.scored_at must be ISO 8601"
    )


# ---------------------------------------------------------------------------
# VeteranReferral — append-only per PRD §2.4.
# ---------------------------------------------------------------------------
def assert_veteran_referral(data: Dict[str, Any]) -> None:
    """PRD §3.1 / §2.4: VeteranReferral carries only id and created_at."""
    _assert_appendonly_fields(data, "VeteranReferral")
    assert is_valid_uuid(data.get("patient_id", "")), (
        "VeteranReferral.patient_id must be a UUID"
    )
    assert isinstance(data.get("referring_va_facility_code"), str), (
        "VeteranReferral.referring_va_facility_code must be a string"
    )
    assert isinstance(data.get("authorized_units"), int), (
        "VeteranReferral.authorized_units must be an integer"
    )
    assert isinstance(data.get("valid_from"), str), (
        "VeteranReferral.valid_from must be a date string"
    )
    assert isinstance(data.get("valid_through"), str), (
        "VeteranReferral.valid_through must be a date string"
    )
    assert data.get("status") in VETERAN_REFERRAL_STATUSES, (
        f"VeteranReferral.status must be one of "
        f"{VETERAN_REFERRAL_STATUSES}, got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Cap status read response — PRD §2.8.
# ---------------------------------------------------------------------------
def assert_cap_status(data: Dict[str, Any]) -> None:
    """PRD §2.8: "The cap-status read endpoint exposes the patient's
    ytd_capped_amount_cents together with three derived values:
    remaining_to_threshold_cents is the maximum of zero and (241,000
    cents minus the year-to-date amount); remaining_to_hard_cap_cents
    is the maximum of zero and (300,000 cents minus the year-to-date
    amount); and kx_required is true when the year-to-date amount is
    strictly greater than 241,000 cents.\""""
    assert isinstance(data.get("ytd_capped_amount_cents"), int), (
        "cap-status.ytd_capped_amount_cents must be an integer"
    )
    assert isinstance(data.get("remaining_to_threshold_cents"), int), (
        "cap-status.remaining_to_threshold_cents must be an integer"
    )
    assert data["remaining_to_threshold_cents"] >= 0, (
        "cap-status.remaining_to_threshold_cents must be >= 0"
    )
    assert isinstance(data.get("remaining_to_hard_cap_cents"), int), (
        "cap-status.remaining_to_hard_cap_cents must be an integer"
    )
    assert data["remaining_to_hard_cap_cents"] >= 0, (
        "cap-status.remaining_to_hard_cap_cents must be >= 0"
    )
    assert isinstance(data.get("kx_required"), bool), (
        "cap-status.kx_required must be a boolean"
    )


# ---------------------------------------------------------------------------
# Version helpers — PRD §2.4.
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(new_version: int,
                                      old_version: int) -> None:
    """PRD §2.4: "Every successful mutation increments version by 1\""""
    assert new_version == old_version + 1, (
        f"version expected to advance by exactly 1, "
        f"got old={old_version} new={new_version}"
    )


__all__ = [
    "PATIENT_STATUSES",
    "INSURANCE_TYPES",
    "THERAPIST_CREDENTIALS",
    "THERAPIST_STATUSES",
    "EPISODE_STATUSES",
    "BODY_REGIONS",
    "CAP_POLICIES",
    "DISCHARGE_OUTCOMES",
    "EVALUATION_STATUSES",
    "EVALUATION_TYPES",
    "EVALUATION_COMPLEXITIES",
    "PLAN_OF_CARE_STATUSES",
    "AUTHORIZATION_STATUSES",
    "AUTHORIZATION_SOURCES",
    "VISIT_STATUSES",
    "HEP_STATUSES",
    "DISCHARGE_ASSESSMENT_STATUSES",
    "MIPS_MEASURE_CODES",
    "MIPS_EXCEPTION_REASONS",
    "VETERAN_REFERRAL_STATUSES",
    "assert_patient",
    "assert_therapist",
    "assert_episode",
    "assert_episode_unit_invariant",
    "assert_evaluation",
    "assert_plan_of_care",
    "assert_authorization",
    "assert_visit",
    "assert_home_exercise_program",
    "assert_discharge_assessment",
    "assert_mips_measure",
    "assert_veteran_referral",
    "assert_cap_status",
    "assert_version_incremented_by_one",
]
