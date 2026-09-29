"""Entity assertions and domain invariant checkers for this PRD."""

from datetime import datetime

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AcuityTier,
    BedStatus,
    BedType,
    BundleActivationStatus,
    CareAssignmentStatus,
    CertLevel,
    CesareanEventStatus,
    CesareanReadinessState,
    ChecklistItemStatus,
    CoverageMode,
    CredentialType,
    DrillCurrencyState,
    DrillStatus,
    EmploymentStatus,
    EscalationStatus,
    FetalCategory,
    IndicationCode,
    InductionBookingStatus,
    LaborPhase,
    PriorityClass,
    ReviewStatus,
    RoleSlot,
    ShiftAssignmentStatus,
    SnapshotStatus,
    StaffRole,
    StaffingPosture,
    StaffingState,
    SupportPassStatus,
)


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict):
    """Every entity in this API carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer: {data.get('version')!r}"
    )


def assert_one_decimal(value, label="value"):
    """Coverage and acuity figures are carried to one decimal place."""
    assert value == pytest.approx(round(value, 1), abs=1e-9), (
        f"{label} must carry at most one decimal place, got {value}"
    )


def assert_obstetric_unit(data: dict):
    assert_common_fields(data)
    assert isinstance(data["unit_name"], str) and 1 <= len(data["unit_name"]) <= 120
    assert data["licensed_ldr_beds"] >= 1
    assert data["licensed_or_rooms"] >= 1
    assert data["max_daily_induction_bed_minutes"] >= 0
    assert data["staffing_posture"] in _values(StaffingPosture)
    assert data["cesarean_readiness_state"] in _values(CesareanReadinessState)
    assert data["coverage_deficit_units"] >= 0
    assert_one_decimal(data["coverage_deficit_units"], "coverage_deficit_units")
    assert data["escalation_breach_count"] >= 0
    assert data["bundle_breach_count"] >= 0
    assert data["turnover_buffer_minutes"] in (45, 75)
    assert isinstance(data["committed_bed_minutes_by_day"], dict)
    assert isinstance(data["held_bed_minutes_by_day"], dict)
    if data.get("last_capacity_sweep_at") is not None:
        assert is_iso8601_timestamp(data["last_capacity_sweep_at"])


def assert_staff_member(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert data["staff_role"] in _values(StaffRole)
    assert data["fetal_monitoring_cert_level"] in _values(CertLevel)
    assert is_iso8601_timestamp(data["credential_expires_at"])
    assert isinstance(data["or_circulating_qualified"], bool)
    assert data["employment_status"] in _values(EmploymentStatus)
    assert data["drill_currency_state"] in _values(DrillCurrencyState)


def assert_shift_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["staff_id"])
    assert data["role_slot"] in _values(RoleSlot)
    assert is_iso8601_timestamp(data["shift_start_utc"])
    assert is_iso8601_timestamp(data["shift_end_utc"])
    assert data["shift_end_utc"] > data["shift_start_utc"]
    assert data["status"] in _values(ShiftAssignmentStatus)
    assert data["assigned_acuity_load_units"] >= 0
    assert_one_decimal(data["assigned_acuity_load_units"], "assigned_acuity_load_units")
    if data.get("capacity_units_effective") is not None:
        assert data["capacity_units_effective"] >= 0
        assert_one_decimal(data["capacity_units_effective"], "capacity_units_effective")


def assert_bed(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert isinstance(data["bed_label"], str) and 1 <= len(data["bed_label"]) <= 40
    assert data["bed_type"] in _values(BedType)
    assert data["status"] in _values(BedStatus)
    if data["status"] in (BedStatus.AVAILABLE.value, BedStatus.HELD.value):
        assert data.get("current_encounter_id") is None
    if data["status"] != BedStatus.HELD.value:
        assert data.get("held_booking_id") is None
    if data["status"] != BedStatus.TURNOVER.value:
        assert data.get("turnover_clear_at") is None


def assert_labor_encounter(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert isinstance(data["patient_record_code"], str) and data["patient_record_code"]
    assert data["labor_phase"] in _values(LaborPhase)
    assert data["staffing_state"] in _values(StaffingState)
    assert data["parity"] >= 0
    assert 20 <= data["gestational_age_weeks"] <= 44
    assert data["fetus_count"] >= 1
    assert isinstance(data["prior_cesarean"], bool)
    assert isinstance(data["is_ntsv"], bool)
    assert data["acuity_tier"] in _values(AcuityTier)
    assert isinstance(data["one_to_one_required"], bool)
    assert data["required_coverage_units"] >= 0
    assert_one_decimal(data["required_coverage_units"], "required_coverage_units")
    assert data["assigned_coverage_units"] >= 0
    assert_one_decimal(data["assigned_coverage_units"], "assigned_coverage_units")
    assert isinstance(data["magnesium_infusion_active"], bool)
    assert is_iso8601_timestamp(data["admitted_at"])


def assert_care_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["encounter_id"])
    assert is_valid_uuid(data["shift_assignment_id"])
    assert is_valid_uuid(data["staff_id"])
    assert data["coverage_mode"] in _values(CoverageMode)
    assert data["status"] in _values(CareAssignmentStatus)
    assert data["acuity_units_consumed"] >= 0
    assert_one_decimal(data["acuity_units_consumed"], "acuity_units_consumed")
    if data["status"] == CareAssignmentStatus.ACTIVE.value:
        assert data.get("released_at") is None


def assert_induction_booking(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert data["indication_code"] in _values(IndicationCode)
    assert data["priority_class"] in _values(PriorityClass)
    assert data["status"] in _values(InductionBookingStatus)
    assert 60 <= data["expected_labor_minutes"] <= 2160
    assert 20 <= data["gestational_age_weeks"] <= 44
    assert is_iso8601_timestamp(data["requested_start_utc"])
    assert data["bump_count"] >= 0
    if data["status"] != InductionBookingStatus.CAPACITY_HELD.value:
        assert data.get("hold_expires_at") is None


def assert_bundle_activation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["encounter_id"])
    assert data["status"] in _values(BundleActivationStatus)
    assert 0 <= data["highest_stage_reached"] <= 3
    assert data["on_time_step_count"] >= 0
    assert data["late_step_count"] >= 0
    assert data["missed_step_count"] >= 0
    assert is_iso8601_timestamp(data["activated_at"])
    for field in ("timeliness_score", "sequence_adjusted_score"):
        if data.get(field) is not None:
            assert 0.0 <= data[field] <= 100.0
            assert_cost_precision(data[field], 2)


def assert_checklist_item(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["activation_id"])
    assert data["status"] in _values(ChecklistItemStatus)
    assert data["step_sequence"] >= 1
    assert 1 <= data["stage_gate"] <= 3
    assert data["required_within_minutes"] >= 1
    assert is_iso8601_timestamp(data["due_at_activation_anchored"])
    if data["status"] == ChecklistItemStatus.PENDING.value:
        assert data.get("completed_at") is None
        assert data.get("minutes_from_activation") is None


def assert_fetal_assessment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["encounter_id"])
    assert data["category"] in _values(FetalCategory)
    assert 50 <= data["baseline_rate_bpm"] <= 220
    assert data["escalation_status"] in _values(EscalationStatus)
    assert 0 <= data["escalation_tier_high_water"] <= 3
    assert is_iso8601_timestamp(data["assessed_at"])
    if data["escalation_status"] == EscalationStatus.NOT_REQUIRED.value:
        assert data.get("escalation_due_at") is None


def assert_cesarean_event(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["encounter_id"])
    assert data["status"] in _values(CesareanEventStatus)
    assert is_iso8601_timestamp(data["decision_at"])
    assert isinstance(data["mobilized_staff_ids"], list)
    if data.get("incision_at") is None:
        assert data.get("decision_to_incision_minutes") is None
        assert data.get("met_target") is None


def assert_drill(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert data["status"] in _values(DrillStatus)
    assert isinstance(data["participant_staff_ids"], list)
    assert 2 <= len(data["participant_staff_ids"]) <= 20
    assert data["revision_count"] >= 0
    if data["status"] != DrillStatus.VALIDATED.value:
        assert data.get("expires_at") is None


def assert_newborn_review(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["encounter_id"])
    assert is_valid_uuid(data["facilitator_staff_id"])
    assert data["status"] in _values(ReviewStatus)
    assert is_iso8601_timestamp(data["opened_at"])
    assert is_iso8601_timestamp(data["debrief_due_at"])
    assert data["rework_count"] >= 0


def assert_support_pass(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["encounter_id"])
    assert data["credential_type"] in _values(CredentialType)
    assert data["status"] in _values(SupportPassStatus)
    assert is_iso8601_timestamp(data["valid_until"])
    assert data["reentry_count"] >= 0


def assert_snapshot(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert data["status"] in _values(SnapshotStatus)
    assert data["attribution_basis"] == "DELIVERY_COHORT"
    assert data["period_end_utc"] > data["period_start_utc"]
    for numerator, denominator, rate in (
        ("ntsv_cesarean_numerator", "ntsv_cesarean_denominator", "ntsv_cesarean_rate_pct"),
        ("episiotomy_numerator", "episiotomy_denominator", "episiotomy_rate_pct"),
    ):
        assert data[numerator] >= 0
        assert data[denominator] >= 0
        assert data[numerator] <= data[denominator]
        if data[denominator] == 0:
            assert data[rate] is None, f"{rate} must be null on an empty denominator"


def assert_envelope_meta(body: dict):
    """The response envelope carries a request id and an ISO 8601 timestamp."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must carry the req_ prefix: {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, with or without fractional seconds."""
    assert isinstance(value, str), f"expected an ISO 8601 instant, got {value!r}"
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def assert_instant_equals(actual, expected: str, label: str = "instant"):
    """Compare two UTC instants by value rather than by string spelling."""
    assert actual is not None, f"{label} must not be null (expected {expected})"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label} should be {expected}, got {actual}"
    )


def assert_instant_is_null(actual, label: str = "instant"):
    assert actual is None, f"{label} must be null, got {actual!r}"


def minutes_between(start: str, end: str) -> int:
    """Whole minutes from start to end, with the remainder discarded."""
    delta = parse_instant(end) - parse_instant(start)
    return int(delta.total_seconds() // 60)
