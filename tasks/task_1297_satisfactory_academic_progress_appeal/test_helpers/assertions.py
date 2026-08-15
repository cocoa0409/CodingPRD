"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    """Validate a Program record against the PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["required_credits"], int) and data["required_credits"] > 0
    assert isinstance(data["min_gpa"], (int, float))
    assert isinstance(data["min_pace_pct"], (int, float))
    assert isinstance(data["appeal_window_days"], int)
    assert isinstance(data["reminder_offset_days"], list)


def assert_student(data: dict):
    """Validate a Student record against the PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["student_number"], str) and len(data["student_number"]) > 0
    assert isinstance(data["full_name"], str)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert data["sap_status"] in [
        "GOOD_STANDING", "WARNING", "SUSPENSION", "PROBATION", "PLAN_PENDING", "PLAN_ACTIVE",
    ]
    assert isinstance(data["cumulative_attempted_credits"], int)
    assert isinstance(data["cumulative_earned_credits"], int)
    assert isinstance(data["cumulative_quality_points"], (int, float))
    assert isinstance(data["cumulative_gpa_hours"], int)
    assert data["cumulative_gpa"] is None or isinstance(data["cumulative_gpa"], (int, float))
    assert data["pace_pct"] is None or isinstance(data["pace_pct"], (int, float))
    assert isinstance(data["max_tf_exceeded"], bool)


def assert_term(data: dict):
    """Validate a Term record against the PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["seq"], int)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["status"] in ["OPEN", "GRADING_CLOSED", "EVALUATED"]


def assert_enrollment(data: dict):
    """Validate a TermEnrollment record against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("term_id", ""))
    assert isinstance(data["attempted_credits"], int)
    assert data["status"] in ["IN_PROGRESS", "POSTED", "AMENDED"]
    assert isinstance(data["amendment_count"], int)
    if data["status"] == "IN_PROGRESS":
        assert data.get("earned_credits") is None
        assert data.get("quality_points") is None
        assert data.get("gpa_hours") is None
    else:
        assert isinstance(data["earned_credits"], int)
        assert isinstance(data["quality_points"], (int, float))
        assert isinstance(data["gpa_hours"], int)


def assert_evaluation(data: dict):
    """Validate a SapEvaluation record against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("term_id", ""))
    assert data["status"] in ["OFFICIAL", "SUPERSEDED"]
    assert data["pace_pct"] is None or isinstance(data["pace_pct"], (int, float))
    assert data["cumulative_gpa"] is None or isinstance(data["cumulative_gpa"], (int, float))
    assert isinstance(data["max_tf_headroom_credits"], int)
    assert isinstance(data["max_tf_exceeded"], bool)
    assert data["prior_standing"] in [
        "GOOD_STANDING", "WARNING", "SUSPENSION", "PROBATION", "PLAN_PENDING", "PLAN_ACTIVE",
    ]
    assert data["result_standing"] in [
        "GOOD_STANDING", "WARNING", "SUSPENSION", "PROBATION", "PLAN_PENDING", "PLAN_ACTIVE",
    ]
    assert is_iso8601_timestamp(data.get("evaluated_at", "")), "evaluated_at must be ISO 8601"


def assert_appeal(data: dict):
    """Validate an Appeal record against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("sap_evaluation_id", ""))
    assert data["reason_category"] in ["MEDICAL", "FAMILY_EMERGENCY", "MILITARY", "OTHER"]
    assert isinstance(data["statement"], str)
    assert isinstance(data["documents"], list) and len(data["documents"]) >= 1
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUESTED", "APPROVED", "DENIED", "SUPERSEDED",
    ]
    assert is_iso8601_timestamp(data.get("submitted_at", "")), "submitted_at must be ISO 8601"


def assert_plan(data: dict):
    """Validate an AcademicPlan record against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("appeal_id", ""))
    assert is_valid_uuid(data.get("start_term_id", ""))
    assert isinstance(data["total_required_credits"], int)
    assert isinstance(data["coverage_start_seq"], int)
    assert isinstance(data["coverage_end_seq_exclusive"], int)
    assert data["coverage_end_seq_exclusive"] > data["coverage_start_seq"]
    assert data["status"] in ["ACTIVE", "COMPLETED", "FAILED"]


def assert_checkpoint(data: dict):
    """Validate a PlanCheckpoint record against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plan_id", ""))
    assert is_valid_uuid(data.get("term_id", ""))
    assert isinstance(data["required_term_gpa"], (int, float))
    assert isinstance(data["required_term_pace_pct"], (int, float))
    assert isinstance(data["required_earned_credits"], int)
    assert data["outcome"] in ["PENDING", "MET", "MISSED"]


def assert_notification(data: dict):
    """Validate a Notification record against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("student_id", ""))
    assert data["kind"] in [
        "STANDING_CHANGE", "APPEAL_DEADLINE_REMINDER", "APPEAL_DECISION",
        "PLAN_RESULT", "REINSTATEMENT",
    ]
    assert isinstance(data["detail"], str)
    assert is_iso8601_timestamp(data.get("scheduled_at", "")), "scheduled_at must be ISO 8601"
    assert data["status"] in ["QUEUED", "SENT", "CANCELLED"]
    if data["status"] == "QUEUED":
        assert data.get("sent_at") is None


def assert_audit_event(data: dict):
    """Validate an AuditEvent record against the PRD contract.

    Audit rows are immutable once appended: they carry only `id` and
    `created_at`; both `updated_at` and `version` are absent (PRD section 2.5).
    """
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "audit rows must not carry updated_at"
    assert "version" not in data, "audit rows must not carry version"
    assert isinstance(data["actor_role"], str) and len(data["actor_role"]) > 0
    assert isinstance(data["actor_id"], str) and len(data["actor_id"]) > 0
    assert isinstance(data["action"], str) and len(data["action"]) > 0
    assert isinstance(data["entity_type"], str) and len(data["entity_type"]) > 0
    assert isinstance(data["entity_id"], str) and len(data["entity_id"]) > 0
    assert is_iso8601_timestamp(data.get("occurred_at", "")), "occurred_at must be ISO 8601"


def assert_student_credit_ledger(data: dict):
    """Cumulative credit counters are non-negative and coherent."""
    assert data["cumulative_attempted_credits"] >= 0
    assert data["cumulative_earned_credits"] >= 0
    assert data["cumulative_earned_credits"] <= data["cumulative_attempted_credits"]
    assert data["cumulative_gpa_hours"] >= 0
    assert data["cumulative_quality_points"] >= 0
    if data["cumulative_attempted_credits"] == 0:
        assert data["pace_pct"] is None
    if data["cumulative_gpa_hours"] == 0:
        assert data["cumulative_gpa"] is None
