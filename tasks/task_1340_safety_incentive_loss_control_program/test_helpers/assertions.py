"""Entity assertions and domain invariant checkers."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ActionItemStatus,
    AwardStatus,
    AwardTier,
    ClaimKind,
    ClaimStatus,
    ComputedDecision,
    ContractorStatus,
    ControlStatus,
    EmployeeStatus,
    EventSourceType,
    HazardStatus,
    MeetingStatus,
    ObservationKind,
    ObservationStatus,
    Posture,
    ProgramStatus,
    RecommendationPriority,
    RecommendationStatus,
    RiskBand,
    ScoringVariant,
    TrainingAssignmentStatus,
    TrainingSource,
)

_HAZARD_CLASSES = ["LOW", "MODERATE", "HIGH"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_append_only_fields(data: dict):
    """Point-ledger entries and valuation snapshots carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, "append-only resource must not expose updated_at"
    assert "version" not in data, "append-only resource must not expose version"


def _assert_optional_str(data: dict, field: str):
    if data.get(field) is not None:
        assert isinstance(data[field], str), f"{field} must be a string when present"


def assert_iso_instant_equal(actual, expected):
    """Compare two ISO-8601 instants semantically (tolerates .000Z formatting)."""
    def _parse(value):
        assert isinstance(value, str), f"expected ISO string, got {value!r}"
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert _parse(actual) == _parse(expected), f"expected instant {expected}, got {actual}"


def assert_safety_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_year"], int)
    assert data["scoring_variant"] in [v.value for v in ScoringVariant]
    assert isinstance(data["incentive_budget_cents"], int)
    assert isinstance(data["remaining_budget_cents"], int)
    assert isinstance(data["observation_target_rate"], (int, float))
    assert isinstance(data["near_miss_floor_ratio"], (int, float))
    assert isinstance(data["quorum_min"], int)
    assert isinstance(data["exposure_hours"], int)
    assert isinstance(data["payroll_by_class"], list)
    assert isinstance(data["elr_by_class"], list)
    assert data["status"] in [s.value for s in ProgramStatus]
    assert data["posture"] in [p.value for p in Posture]
    assert isinstance(data["overdue_control_count"], int)
    assert isinstance(data["sla_breach_count"], int)
    assert isinstance(data["integrity_flag"], bool)
    assert isinstance(data["sweep_index"], int)


def assert_job_role(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["hazard_class"] in _HAZARD_CLASSES
    assert isinstance(data["required_course_ids"], list)


def assert_training_course(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["title"], str) and data["title"]
    assert data["hazard_class"] in _HAZARD_CLASSES
    assert isinstance(data["validity_months"], int) and data["validity_months"] > 0
    assert isinstance(data["renewal_window_days"], int)


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data.get("job_role_id", ""))
    assert isinstance(data["hired_on"], str)
    assert isinstance(data["committee_member"], bool)
    assert data["status"] in [s.value for s in EmployeeStatus]
    assert isinstance(data["pending_required_training_count"], int)
    assert data["pending_required_training_count"] >= 0


def assert_training_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["due_date"], str)
    assert isinstance(data["required"], bool)
    assert data["source"] in [s.value for s in TrainingSource]
    assert data["status"] in [s.value for s in TrainingAssignmentStatus]
    _assert_optional_str(data, "completed_at")
    _assert_optional_str(data, "cert_valid_until")


def assert_hazard(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["location"], str)
    assert isinstance(data["description"], str)
    assert is_valid_uuid(data.get("identified_by", ""))
    assert data["status"] in [s.value for s in HazardStatus]
    assert isinstance(data["sla_breached"], bool)
    assert isinstance(data["overdue_control_count"], int)
    if data.get("severity") is not None:
        assert isinstance(data["severity"], int) and 1 <= data["severity"] <= 5
    if data.get("probability") is not None:
        assert isinstance(data["probability"], int) and 1 <= data["probability"] <= 5
    if data.get("risk_score") is not None:
        assert isinstance(data["risk_score"], int)
        assert data["risk_score"] == data["severity"] * data["probability"]
    if data.get("risk_band") is not None:
        assert data["risk_band"] in [b.value for b in RiskBand]
    _assert_optional_str(data, "response_sla_due")


def assert_control_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("hazard_id", ""))
    assert isinstance(data["description"], str)
    assert is_valid_uuid(data.get("implementer_id", ""))
    assert isinstance(data["due_date"], str)
    assert data["status"] in [s.value for s in ControlStatus]
    _assert_optional_str(data, "implemented_at")
    _assert_optional_str(data, "verified_by")
    _assert_optional_str(data, "verified_at")
    _assert_optional_str(data, "outcome_note")


def assert_observation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("reporter_id", ""))
    assert data["kind"] in [k.value for k in ObservationKind]
    assert isinstance(data["description"], str)
    assert isinstance(data["occurred_at"], str)
    assert data["status"] in [s.value for s in ObservationStatus]
    _assert_optional_str(data, "linked_hazard_id")


def assert_committee_meeting(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["scheduled_start"], str)
    assert isinstance(data["scheduled_end"], str)
    assert isinstance(data["location"], str)
    assert isinstance(data["open_action_count"], int)
    assert data["open_action_count"] >= 0
    assert data["status"] in [s.value for s in MeetingStatus]
    if data.get("attendee_ids") is not None:
        assert isinstance(data["attendee_ids"], list)
    _assert_optional_str(data, "minutes_text")


def assert_action_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("meeting_id", ""))
    assert is_valid_uuid(data.get("assignee_id", ""))
    assert isinstance(data["description"], str)
    assert isinstance(data["due_date"], str)
    assert data["status"] in [s.value for s in ActionItemStatus]
    _assert_optional_str(data, "hazard_id")
    _assert_optional_str(data, "completed_at")
    _assert_optional_str(data, "verified_by")


def assert_contractor_org(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str)
    assert isinstance(data["emr"], (int, float))
    assert isinstance(data["trir"], (int, float))
    assert isinstance(data["safety_audit_pct"], (int, float))
    assert isinstance(data["insurance_cert_expires_on"], str)
    assert data["status"] in [s.value for s in ContractorStatus]
    if data.get("prequal_score") is not None:
        assert isinstance(data["prequal_score"], (int, float))
    if data.get("computed_decision") is not None:
        assert data["computed_decision"] in [d.value for d in ComputedDecision]
    _assert_optional_str(data, "prequal_valid_until")
    _assert_optional_str(data, "suspension_reason")
    _assert_optional_str(data, "suspension_claim_id")


def assert_claim_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["occurred_on"], str)
    assert data["kind"] in [k.value for k in ClaimKind]
    assert isinstance(data["incurred_cents"], int)
    assert isinstance(data["effective_incurred_cents"], int)
    assert data["status"] in [s.value for s in ClaimStatus]
    _assert_optional_str(data, "employee_id")
    _assert_optional_str(data, "contractor_org_id")


def assert_recommendation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["carrier_name"], str)
    assert data["priority"] in [p.value for p in RecommendationPriority]
    assert isinstance(data["description"], str)
    assert isinstance(data["due_date"], str)
    assert data["status"] in [s.value for s in RecommendationStatus]
    _assert_optional_str(data, "response_text")
    _assert_optional_str(data, "evidence_control_id")
    _assert_optional_str(data, "responded_by")
    _assert_optional_str(data, "reviewed_by")
    _assert_optional_str(data, "review_note")


def assert_incentive_award(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("employee_id", ""))
    assert isinstance(data["points_earned"], int) and data["points_earned"] >= 1
    assert data["tier"] in [t.value for t in AwardTier]
    assert isinstance(data["payout_cents"], int) and data["payout_cents"] >= 0
    assert data["status"] in [s.value for s in AwardStatus]
    _assert_optional_str(data, "void_reason")


def assert_incentive_event(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("employee_id", ""))
    assert data["source_type"] in [s.value for s in EventSourceType]
    assert isinstance(data["points_base"], int)
    assert isinstance(data["hazard_class_multiplier"], (int, float))
    assert isinstance(data["timeliness_multiplier"], (int, float))
    assert isinstance(data["points_awarded"], int)
    assert isinstance(data["reference_id"], str) and data["reference_id"]


def assert_emr_forecast(data: dict):
    _assert_append_only_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["as_of"], str)
    assert isinstance(data["payroll_factor"], (int, float))
    for field in ("expected_losses_provisional_cents", "expected_losses_final_cents",
                  "ballast_provisional_cents", "ballast_final_cents",
                  "actual_primary_provisional_cents", "actual_excess_provisional_cents",
                  "actual_primary_final_cents", "actual_excess_final_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
        assert data[field] >= 0, f"{field} must be non-negative"
    assert isinstance(data["weighting_w"], (int, float))
    assert 0.05 <= data["weighting_w"] <= 0.75
    assert isinstance(data["emr_provisional"], (int, float))
    assert isinstance(data["emr_final"], (int, float))


def assert_program_budget_invariant(program: dict, reserved_or_paid_payouts: int):
    """remaining_budget_cents == incentive_budget_cents - payouts of APPROVED|PAID."""
    assert program["remaining_budget_cents"] == (
        program["incentive_budget_cents"] - reserved_or_paid_payouts
    ), (
        f"budget invariant broken: remaining {program['remaining_budget_cents']} != "
        f"budget {program['incentive_budget_cents']} - {reserved_or_paid_payouts}"
    )
