"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerant of optional fractional digits."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_timestamp_instant(actual: str, expected: str):
    """Compare two timestamps as instants, not as strings.

    PRD §2.4 pins the three-fractional-digit serialization only for
    `created_at`/`updated_at` (and §2.2 for `api_request_timestamp`); the
    serialization of domain timestamps (`due_at`, `completed_at`, `closed_at`)
    is not pinned, while their *instant* values are (e.g. §3.4 "due exactly the
    current tier's cadence after the approval instant"). Comparing parsed
    instants keeps the PRD-covered rule at full strength without depending on
    the unpinned string form.
    """
    assert _parse_instant(actual) == _parse_instant(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def _assert_common_fields(data: dict, entity_label: str):
    """PRD §2.4: every resource carries id / created_at / updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be int"


def assert_student(data: dict):
    _assert_common_fields(data, "Student")
    assert isinstance(data["external_ref"], str) and data["external_ref"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["enrollment_status"] in ("ENROLLED", "LEAVE_OF_ABSENCE", "WITHDRAWN")


def assert_staff_member(data: dict):
    _assert_common_fields(data, "StaffMember")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["office"] in (
        "FACULTY_AFFAIRS", "RESIDENCE_LIFE", "COUNSELING_CENTER",
        "DEAN_OF_STUDENTS", "BIT_OFFICE", "CAMPUS_SAFETY", "PRIVACY_OFFICE",
    )
    assert isinstance(data["active"], bool)


def assert_concern_report(data: dict):
    _assert_common_fields(data, "ConcernReport")
    assert isinstance(data["student_id"], str) and data["student_id"]
    assert isinstance(data["reporter_id"], str) and data["reporter_id"]
    assert data["category"] in (
        "ACADEMIC_DISTRESS", "BEHAVIORAL_THREAT", "SELF_HARM_RISK",
        "SUBSTANCE_CONCERN", "WELLBEING_GENERAL",
    )
    assert isinstance(data["narrative"], str)
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "ACCEPTED", "CLOSED_NO_ACTION")


def assert_care_case(data: dict):
    _assert_common_fields(data, "CareCase")
    assert isinstance(data["student_id"], str) and data["student_id"]
    assert isinstance(data["opened_from_report_id"], str) and data["opened_from_report_id"]
    assert isinstance(data["assigned_case_manager_id"], str)
    assert data["status"] in (
        "INTAKE", "TRIAGED", "PLAN_DRAFTING", "PLAN_ACTIVE", "MANDATED_ASSESSMENT",
        "LEAVE_DECISION", "ON_LEAVE", "REENTRY_REVIEW", "CLOSED",
    )
    # PRD §2.6: current_risk_score / current_risk_tier are null until first scoring.
    if data.get("current_risk_score") is not None:
        assert isinstance(data["current_risk_score"], (int, float))
    if data.get("current_risk_tier") is not None:
        assert data["current_risk_tier"] in ("LOW", "MODERATE", "HIGH", "IMMINENT")
    assert isinstance(data["consecutive_stable_checkins"], int)


def assert_risk_scoring(data: dict):
    _assert_common_fields(data, "RiskScoring")
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert data["mode"] in ("INITIAL", "REASSESSMENT")
    for dim in ("harm_to_self", "harm_to_others", "academic_disruption", "substance_involvement"):
        assert isinstance(data[dim], int), f"RiskScoring.{dim} must be int"
        assert 0 <= data[dim] <= 25, f"RiskScoring.{dim} must be within 0..25"
    assert isinstance(data["score"], (int, float))
    assert data["tier"] in ("LOW", "MODERATE", "HIGH", "IMMINENT")


def assert_intervention_plan(data: dict):
    _assert_common_fields(data, "InterventionPlan")
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["drafted_by"], str) and data["drafted_by"]
    assert isinstance(data["objectives"], list) and len(data["objectives"]) > 0
    assert isinstance(data["success_criteria"], str)
    assert data["status"] in ("DRAFT", "PENDING_APPROVAL", "ACTIVE", "SUPERSEDED", "SUSPENDED")


def assert_mandated_assessment(data: dict):
    _assert_common_fields(data, "MandatedAssessment")
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["ordered_by"], str) and data["ordered_by"]
    assert isinstance(data["evaluator_id"], str) and data["evaluator_id"]
    assert data["status"] in ("SCHEDULED", "COMPLETED", "EXPIRED")
    if data.get("outcome") is not None:
        assert data["outcome"] in ("CLEARED", "NOT_CLEARED")


def assert_leave_decision(data: dict):
    _assert_common_fields(data, "LeaveDecision")
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["requested_by"], str) and data["requested_by"]
    assert data["status"] in ("PENDING", "GRANTED", "DENIED")
    if data.get("decision") is not None:
        assert data["decision"] in ("GRANT_LEAVE", "DENY_LEAVE")


def assert_reentry_evaluation(data: dict):
    _assert_common_fields(data, "ReentryEvaluation")
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["leave_decision_id"], str) and data["leave_decision_id"]
    assert isinstance(data["petitioned_by"], str) and data["petitioned_by"]
    assert data["status"] in ("PENDING", "APPROVED", "DENIED")
    if data.get("outcome") is not None:
        assert data["outcome"] in ("APPROVED_WITH_CONDITIONS", "DENIED")


def assert_follow_up_checkin(data: dict):
    _assert_common_fields(data, "FollowUpCheckin")
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert is_iso8601_timestamp(data["due_at"])
    assert data["status"] in ("SCHEDULED", "COMPLETED", "MISSED", "CANCELLED")
    if data.get("outcome") is not None:
        assert data["outcome"] in ("STABLE", "ESCALATED")


def assert_disclosure_grant(data: dict):
    _assert_common_fields(data, "DisclosureGrant")
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert data["to_office"] in (
        "FACULTY_AFFAIRS", "RESIDENCE_LIFE", "COUNSELING_CENTER",
        "DEAN_OF_STUDENTS", "BIT_OFFICE", "CAMPUS_SAFETY", "PRIVACY_OFFICE",
    )
    assert data["scope"] in ("SUMMARY_ONLY", "FULL_RECORD", "SAFETY_MINIMUM")
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["auto_approved"], bool)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "REVOKED", "EXPIRED")


def assert_trend_report(data: dict):
    _assert_common_fields(data, "TrendReport")
    assert isinstance(data["term_code"], str) and data["term_code"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["variant"] in ("ENTRY_COHORT", "ACTIVE_IN_WINDOW")
    assert isinstance(data["total_cases"], int)
    assert isinstance(data["closed_in_window"], int)
    assert isinstance(data["closure_rate_pct"], (int, float))
    assert isinstance(data["avg_days_to_close"], (int, float))
    dist = data["category_distribution"]
    assert isinstance(dist, dict)
    for cat in (
        "ACADEMIC_DISTRESS", "BEHAVIORAL_THREAT", "SELF_HARM_RISK",
        "SUBSTANCE_CONCERN", "WELLBEING_GENERAL",
    ):
        assert cat in dist, f"category_distribution missing {cat}"
        assert isinstance(dist[cat], (int, float))


def assert_case_read_redacted(data: dict):
    """PRD §2.7: the redacted case view contains exactly five fields."""
    assert set(data.keys()) == {
        "id", "student_id", "status", "current_risk_tier", "current_risk_score",
    }, f"Redacted view must contain exactly the five listed fields, got {sorted(data.keys())}"


def assert_score_precision(value, expected):
    """PRD §2.6: scores are recorded at exactly one decimal place, round-half-up."""
    assert value == expected, f"Expected score {expected}, got {value}"
