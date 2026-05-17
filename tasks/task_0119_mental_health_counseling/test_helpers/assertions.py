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
THERAPIST_CREDENTIAL_STATUSES = {
    "PROVISIONAL", "ACTIVE", "SUSPENDED", "DEACTIVATED",
}
SUPERVISION_TRACKS = {"PRE_LICENSED", "LICENSED"}
STATE_LICENSE_STATUSES = {"PENDING", "ACTIVE", "EXPIRED", "REVOKED"}
SUPERVISION_ASSIGNMENT_STATUSES = {"ACTIVE", "TERMINATED"}
NETWORK_STATUSES = {"IN_NETWORK", "OUT_OF_NETWORK"}
CONTRACT_MODES = {"DEDUCTIBLE_FIRST", "COPAY_ONLY"}
APPOINTMENT_STATUSES = {
    "SCHEDULED", "HELD", "CHECKED_IN",
    "COMPLETED", "NO_SHOW", "CANCELLED",
}
APPOINTMENT_HOLD_REASONS = {"SAFETY_PLAN_MISSING", "LICENSE_GAP"}
CPT_CODES = {"90791", "90834"}
MODALITIES = {"IN_PERSON", "TELEHEALTH"}
SESSION_STATUSES = {"IN_PROGRESS", "COMPLETED", "VOIDED"}
SESSION_TYPES = {"INTAKE", "INDIVIDUAL"}
CRISIS_RISK_LEVELS = {"LOW", "MODERATE", "HIGH"}
SAFETY_PLAN_STATUSES = {"ACTIVE", "SUPERSEDED", "RESCINDED"}
BILLING_MODES = {"INSURANCE_IN_NETWORK", "SELF_PAY"}
BILLING_CLAIM_STATUSES = {"POSTED", "VOIDED"}
SLIDING_FEE_TIER_VALUES = {20, 40, 60, 80, 100}


# ---------------------------------------------------------------------------
# Common-fields helpers — PRD §2.4.
# ---------------------------------------------------------------------------
def _assert_versioned_common_fields(data: Dict[str, Any], entity: str
                                    ) -> None:
    """Assert id + created_at + updated_at + integer version >= 1."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity}.version must be an integer"
    )
    assert data["version"] >= 1, f"{entity}.version must be >= 1"


def _assert_append_only_common_fields(data: Dict[str, Any], entity: str
                                      ) -> None:
    """Assert id + created_at only — PRD §2.4 append-only entities."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )


# ---------------------------------------------------------------------------
# Therapist — PRD §3.1 / §3.2.
# ---------------------------------------------------------------------------
def assert_therapist(data: Dict[str, Any]) -> None:
    """PRD §3.1: Therapist input fields and lifecycle fields."""
    _assert_versioned_common_fields(data, "Therapist")
    assert isinstance(data.get("full_name"), str) and data["full_name"], (
        "Therapist.full_name must be a non-empty string"
    )
    assert isinstance(data.get("npi"), str), "Therapist.npi must be string"
    assert data.get("credential_status") in THERAPIST_CREDENTIAL_STATUSES, (
        f"Therapist.credential_status must be one of "
        f"{THERAPIST_CREDENTIAL_STATUSES}, got "
        f"{data.get('credential_status')!r}"
    )
    assert data.get("supervision_track") in SUPERVISION_TRACKS, (
        f"Therapist.supervision_track must be one of {SUPERVISION_TRACKS}, "
        f"got {data.get('supervision_track')!r}"
    )
    assert isinstance(data.get("supervision_hours_accrued"), (int, float)), (
        "Therapist.supervision_hours_accrued must be numeric"
    )
    assert isinstance(data.get("licensure_exam_eligible"), bool), (
        "Therapist.licensure_exam_eligible must be bool"
    )
    assert isinstance(data.get("psypact_enrolled"), bool), (
        "Therapist.psypact_enrolled must be bool"
    )
    assert isinstance(data.get("pricing_rack_90791_cents"), int), (
        "Therapist.pricing_rack_90791_cents must be integer cents"
    )
    assert data["pricing_rack_90791_cents"] >= 0, (
        "Therapist.pricing_rack_90791_cents must be >= 0"
    )
    assert isinstance(data.get("pricing_rack_90834_cents"), int), (
        "Therapist.pricing_rack_90834_cents must be integer cents"
    )
    assert data["pricing_rack_90834_cents"] >= 0, (
        "Therapist.pricing_rack_90834_cents must be >= 0"
    )


# ---------------------------------------------------------------------------
# StateLicense — PRD §3.1.
# ---------------------------------------------------------------------------
def assert_state_license(data: Dict[str, Any]) -> None:
    """PRD §3.1: StateLicense fields."""
    _assert_versioned_common_fields(data, "StateLicense")
    assert is_valid_uuid(data.get("therapist_id", "")), (
        "StateLicense.therapist_id must be UUID"
    )
    state_code = data.get("state_code", "")
    assert isinstance(state_code, str) and len(state_code) == 2 and (
        state_code.isupper()
    ), "StateLicense.state_code must be two uppercase letters"
    assert isinstance(data.get("license_number"), str) and (
        data["license_number"]
    ), "StateLicense.license_number must be non-empty string"
    assert data.get("status") in STATE_LICENSE_STATUSES, (
        f"StateLicense.status must be one of {STATE_LICENSE_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    assert isinstance(data.get("issued_on"), str), (
        "StateLicense.issued_on must be ISO datetime string"
    )
    assert isinstance(data.get("expires_on"), str), (
        "StateLicense.expires_on must be ISO datetime string"
    )


# ---------------------------------------------------------------------------
# Supervisor — PRD §3.3.
# ---------------------------------------------------------------------------
def assert_supervisor(data: Dict[str, Any]) -> None:
    """PRD §3.3: Supervisor fields."""
    _assert_versioned_common_fields(data, "Supervisor")
    assert isinstance(data.get("full_name"), str) and data["full_name"], (
        "Supervisor.full_name must be non-empty string"
    )
    home_state = data.get("home_state_code", "")
    assert isinstance(home_state, str) and len(home_state) == 2 and (
        home_state.isupper()
    ), "Supervisor.home_state_code must be two uppercase letters"
    assert isinstance(data.get("active"), bool), (
        "Supervisor.active must be bool"
    )


# ---------------------------------------------------------------------------
# SupervisionAssignment — PRD §3.3 (append-only).
# ---------------------------------------------------------------------------
def assert_supervision_assignment(data: Dict[str, Any]) -> None:
    """PRD §2.4 / §3.3: SupervisionAssignment carries id and created_at
    only — no updated_at, no version."""
    _assert_append_only_common_fields(data, "SupervisionAssignment")
    assert is_valid_uuid(data.get("therapist_id", "")), (
        "SupervisionAssignment.therapist_id must be UUID"
    )
    assert is_valid_uuid(data.get("supervisor_id", "")), (
        "SupervisionAssignment.supervisor_id must be UUID"
    )
    assert isinstance(data.get("started_on"), str), (
        "SupervisionAssignment.started_on must be ISO datetime string"
    )
    assert data.get("status") in SUPERVISION_ASSIGNMENT_STATUSES, (
        f"SupervisionAssignment.status must be one of "
        f"{SUPERVISION_ASSIGNMENT_STATUSES}, got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Patient — PRD §3.4.
# ---------------------------------------------------------------------------
def assert_patient(data: Dict[str, Any]) -> None:
    """PRD §3.4: Patient fields and derived sliding_fee_tier_pct."""
    _assert_versioned_common_fields(data, "Patient")
    assert isinstance(data.get("full_name"), str) and data["full_name"], (
        "Patient.full_name must be non-empty string"
    )
    state = data.get("state_of_residence", "")
    assert isinstance(state, str) and len(state) == 2 and state.isupper(), (
        "Patient.state_of_residence must be two uppercase letters"
    )
    assert isinstance(data.get("household_income_cents"), int), (
        "Patient.household_income_cents must be integer cents"
    )
    assert data["household_income_cents"] >= 0, (
        "Patient.household_income_cents must be >= 0"
    )
    assert isinstance(data.get("household_size"), int), (
        "Patient.household_size must be integer"
    )
    assert data["household_size"] >= 1, (
        "Patient.household_size must be >= 1"
    )
    assert data.get("sliding_fee_tier_pct") in SLIDING_FEE_TIER_VALUES, (
        f"Patient.sliding_fee_tier_pct must be one of "
        f"{SLIDING_FEE_TIER_VALUES}, got {data.get('sliding_fee_tier_pct')!r}"
    )
    plan_id = data.get("insurance_plan_id")
    assert plan_id is None or is_valid_uuid(plan_id), (
        "Patient.insurance_plan_id must be UUID or null"
    )
    assert isinstance(data.get("deductible_remaining_cents"), int), (
        "Patient.deductible_remaining_cents must be integer cents"
    )
    assert data["deductible_remaining_cents"] >= 0, (
        "Patient.deductible_remaining_cents must be >= 0"
    )
    crisis = data.get("latest_crisis_level")
    assert crisis is None or crisis in CRISIS_RISK_LEVELS, (
        f"Patient.latest_crisis_level must be None or one of "
        f"{CRISIS_RISK_LEVELS}, got {crisis!r}"
    )
    assert isinstance(data.get("safety_plan_required"), bool), (
        "Patient.safety_plan_required must be bool"
    )


# ---------------------------------------------------------------------------
# InsurancePlan — PRD §3.5.
# ---------------------------------------------------------------------------
def assert_insurance_plan(data: Dict[str, Any]) -> None:
    """PRD §3.5: InsurancePlan fields."""
    _assert_versioned_common_fields(data, "InsurancePlan")
    assert isinstance(data.get("payer_name"), str) and data["payer_name"], (
        "InsurancePlan.payer_name must be non-empty string"
    )
    assert isinstance(data.get("plan_code"), str) and data["plan_code"], (
        "InsurancePlan.plan_code must be non-empty string"
    )
    assert data.get("network_status") in NETWORK_STATUSES, (
        f"InsurancePlan.network_status must be one of {NETWORK_STATUSES}, "
        f"got {data.get('network_status')!r}"
    )
    assert data.get("contract_mode") in CONTRACT_MODES, (
        f"InsurancePlan.contract_mode must be one of {CONTRACT_MODES}, "
        f"got {data.get('contract_mode')!r}"
    )
    for field in (
        "allowed_amount_90791_cents",
        "allowed_amount_90834_cents",
        "copay_cents",
    ):
        assert isinstance(data.get(field), int), (
            f"InsurancePlan.{field} must be integer cents"
        )
        assert data[field] >= 0, f"InsurancePlan.{field} must be >= 0"


# ---------------------------------------------------------------------------
# Appointment — PRD §3.6.
# ---------------------------------------------------------------------------
def assert_appointment(data: Dict[str, Any]) -> None:
    """PRD §3.6: Appointment fields."""
    _assert_versioned_common_fields(data, "Appointment")
    assert is_valid_uuid(data.get("therapist_id", "")), (
        "Appointment.therapist_id must be UUID"
    )
    assert is_valid_uuid(data.get("patient_id", "")), (
        "Appointment.patient_id must be UUID"
    )
    assert data.get("cpt_code") in CPT_CODES, (
        f"Appointment.cpt_code must be one of {CPT_CODES}, "
        f"got {data.get('cpt_code')!r}"
    )
    assert data.get("modality") in MODALITIES, (
        f"Appointment.modality must be one of {MODALITIES}, "
        f"got {data.get('modality')!r}"
    )
    state = data.get("patient_state_on_day", "")
    assert isinstance(state, str) and len(state) == 2 and state.isupper(), (
        "Appointment.patient_state_on_day must be two uppercase letters"
    )
    assert isinstance(data.get("scheduled_start"), str), (
        "Appointment.scheduled_start must be ISO datetime string"
    )
    assert isinstance(data.get("scheduled_end"), str), (
        "Appointment.scheduled_end must be ISO datetime string"
    )
    assert data.get("status") in APPOINTMENT_STATUSES, (
        f"Appointment.status must be one of {APPOINTMENT_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    hold_reason = data.get("hold_reason")
    assert hold_reason is None or hold_reason in APPOINTMENT_HOLD_REASONS, (
        f"Appointment.hold_reason must be None or one of "
        f"{APPOINTMENT_HOLD_REASONS}, got {hold_reason!r}"
    )


# ---------------------------------------------------------------------------
# Session — PRD §3.7.
# ---------------------------------------------------------------------------
def assert_session(data: Dict[str, Any]) -> None:
    """PRD §3.7: Session fields."""
    _assert_versioned_common_fields(data, "Session")
    assert is_valid_uuid(data.get("appointment_id", "")), (
        "Session.appointment_id must be UUID"
    )
    assert data.get("type") in SESSION_TYPES, (
        f"Session.type must be one of {SESSION_TYPES}, "
        f"got {data.get('type')!r}"
    )
    assert isinstance(data.get("actual_duration_minutes"), int), (
        "Session.actual_duration_minutes must be integer"
    )
    assert data["actual_duration_minutes"] >= 1, (
        "Session.actual_duration_minutes must be >= 1"
    )
    assert isinstance(data.get("supervision_credit_hours"), (int, float)), (
        "Session.supervision_credit_hours must be numeric"
    )
    assert data.get("status") in SESSION_STATUSES, (
        f"Session.status must be one of {SESSION_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# CrisisAssessment — PRD §3.9 (append-only).
# ---------------------------------------------------------------------------
def assert_crisis_assessment(data: Dict[str, Any]) -> None:
    """PRD §2.4 / §3.9: CrisisAssessment carries id and created_at only."""
    _assert_append_only_common_fields(data, "CrisisAssessment")
    assert is_valid_uuid(data.get("patient_id", "")), (
        "CrisisAssessment.patient_id must be UUID"
    )
    assert is_valid_uuid(data.get("therapist_id", "")), (
        "CrisisAssessment.therapist_id must be UUID"
    )
    for field, lo, hi in (
        ("si_score", 0, 4),
        ("pa_score", 0, 3),
        ("su_score", 0, 2),
        ("so_score", 0, 2),
        ("am_score", 0, 2),
    ):
        v = data.get(field)
        assert isinstance(v, int), f"CrisisAssessment.{field} must be int"
        assert lo <= v <= hi, (
            f"CrisisAssessment.{field}={v} must lie in [{lo}, {hi}]"
        )
    assert isinstance(data.get("composite_score"), (int, float)), (
        "CrisisAssessment.composite_score must be numeric"
    )
    assert data.get("risk_level") in CRISIS_RISK_LEVELS, (
        f"CrisisAssessment.risk_level must be one of "
        f"{CRISIS_RISK_LEVELS}, got {data.get('risk_level')!r}"
    )
    assert isinstance(data.get("assessed_at"), str), (
        "CrisisAssessment.assessed_at must be ISO datetime string"
    )


# ---------------------------------------------------------------------------
# SafetyPlan — PRD §3.9.
# ---------------------------------------------------------------------------
def assert_safety_plan(data: Dict[str, Any]) -> None:
    """PRD §3.9: SafetyPlan fields."""
    _assert_versioned_common_fields(data, "SafetyPlan")
    assert is_valid_uuid(data.get("patient_id", "")), (
        "SafetyPlan.patient_id must be UUID"
    )
    assert is_valid_uuid(data.get("trigger_assessment_id", "")), (
        "SafetyPlan.trigger_assessment_id must be UUID"
    )
    assert isinstance(data.get("warning_signs"), str), (
        "SafetyPlan.warning_signs must be string"
    )
    assert isinstance(data.get("coping_strategies"), str), (
        "SafetyPlan.coping_strategies must be string"
    )
    contacts = data.get("support_contacts")
    assert isinstance(contacts, list) and len(contacts) >= 1, (
        "SafetyPlan.support_contacts must be a list with >= 1 entry"
    )
    for c in contacts:
        assert isinstance(c, dict), (
            "SafetyPlan.support_contacts entry must be object"
        )
    assert isinstance(data.get("crisis_hotline"), str), (
        "SafetyPlan.crisis_hotline must be string"
    )
    assert isinstance(data.get("means_restriction_plan"), str), (
        "SafetyPlan.means_restriction_plan must be string"
    )
    assert data.get("status") in SAFETY_PLAN_STATUSES, (
        f"SafetyPlan.status must be one of {SAFETY_PLAN_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# BillingClaim — PRD §3.7 / §3.8.
# ---------------------------------------------------------------------------
def assert_billing_claim(data: Dict[str, Any]) -> None:
    """PRD §3.7 / §3.8: BillingClaim fields."""
    _assert_versioned_common_fields(data, "BillingClaim")
    assert is_valid_uuid(data.get("appointment_id", "")), (
        "BillingClaim.appointment_id must be UUID"
    )
    assert is_valid_uuid(data.get("patient_id", "")), (
        "BillingClaim.patient_id must be UUID"
    )
    plan_id = data.get("insurance_plan_id")
    assert plan_id is None or is_valid_uuid(plan_id), (
        "BillingClaim.insurance_plan_id must be UUID or null"
    )
    assert data.get("cpt_code") in CPT_CODES, (
        f"BillingClaim.cpt_code must be one of {CPT_CODES}, "
        f"got {data.get('cpt_code')!r}"
    )
    assert data.get("billing_mode") in BILLING_MODES, (
        f"BillingClaim.billing_mode must be one of {BILLING_MODES}, "
        f"got {data.get('billing_mode')!r}"
    )
    for field in (
        "charged_amount_cents",
        "patient_responsibility_cents",
        "insurer_paid_cents",
    ):
        v = data.get(field)
        assert isinstance(v, int), (
            f"BillingClaim.{field} must be integer cents, got {v!r}"
        )
        assert v >= 0, f"BillingClaim.{field} must be >= 0"
    assert data.get("status") in BILLING_CLAIM_STATUSES, (
        f"BillingClaim.status must be one of {BILLING_CLAIM_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    assert isinstance(data.get("posted_at"), str), (
        "BillingClaim.posted_at must be ISO datetime string"
    )


# ---------------------------------------------------------------------------
# Domain invariants — PRD §3.7 / §3.8.
# ---------------------------------------------------------------------------
def assert_in_network_claim_arithmetic(claim: Dict[str, Any]) -> None:
    """PRD §3.7: for INSURANCE_IN_NETWORK claims, insurer_paid_cents
    equals charged_amount_cents - patient_responsibility_cents.

    PRD §3.7: 'insurer_paid_cents is always charged_amount_cents
    minus patient_responsibility_cents for in-network claims, and
    zero for self-pay claims.'
    """
    assert claim["billing_mode"] == "INSURANCE_IN_NETWORK", (
        "Use assert_in_network_claim_arithmetic only on in-network claims"
    )
    expected = claim["charged_amount_cents"] - (
        claim["patient_responsibility_cents"]
    )
    assert claim["insurer_paid_cents"] == expected, (
        f"BillingClaim.insurer_paid_cents={claim['insurer_paid_cents']} "
        f"must equal charged_amount_cents - patient_responsibility_cents "
        f"= {expected}"
    )


def assert_self_pay_claim_arithmetic(claim: Dict[str, Any]) -> None:
    """PRD §3.7: for self-pay claims, insurer_paid_cents is zero and
    patient_responsibility_cents equals charged_amount_cents.

    PRD §3.7: 'The full charge becomes patient_responsibility_cents,
    and insurer_paid_cents is zero.'
    """
    assert claim["billing_mode"] == "SELF_PAY", (
        "Use assert_self_pay_claim_arithmetic only on self-pay claims"
    )
    assert claim["insurer_paid_cents"] == 0, (
        f"Self-pay BillingClaim.insurer_paid_cents must be 0, got "
        f"{claim['insurer_paid_cents']}"
    )
    assert claim["patient_responsibility_cents"] == claim[
        "charged_amount_cents"
    ], (
        "Self-pay BillingClaim.patient_responsibility_cents must equal "
        "charged_amount_cents"
    )


def assert_version_incremented_by_one(before: int, after: int,
                                      entity: str) -> None:
    """PRD §2.4: 'an integer version that begins at 1 and increments by
    exactly 1 on every successful mutation.'"""
    assert after == before + 1, (
        f"{entity}.version expected {before + 1} after mutation, got "
        f"{after} (before={before})"
    )


__all__ = [
    "THERAPIST_CREDENTIAL_STATUSES",
    "SUPERVISION_TRACKS",
    "STATE_LICENSE_STATUSES",
    "SUPERVISION_ASSIGNMENT_STATUSES",
    "NETWORK_STATUSES",
    "CONTRACT_MODES",
    "APPOINTMENT_STATUSES",
    "APPOINTMENT_HOLD_REASONS",
    "CPT_CODES",
    "MODALITIES",
    "SESSION_STATUSES",
    "SESSION_TYPES",
    "CRISIS_RISK_LEVELS",
    "SAFETY_PLAN_STATUSES",
    "BILLING_MODES",
    "BILLING_CLAIM_STATUSES",
    "SLIDING_FEE_TIER_VALUES",
    "assert_therapist",
    "assert_state_license",
    "assert_supervisor",
    "assert_supervision_assignment",
    "assert_patient",
    "assert_insurance_plan",
    "assert_appointment",
    "assert_session",
    "assert_crisis_assessment",
    "assert_safety_plan",
    "assert_billing_claim",
    "assert_in_network_claim_arithmetic",
    "assert_self_pay_claim_arithmetic",
    "assert_version_incremented_by_one",
]
