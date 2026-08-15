"""Entity assertions and domain invariant checkers (PRD §2.5, §2.7, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Every resource carries id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_advisor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["major_codes"], list)
    assert isinstance(data["max_caseload"], int) and data["max_caseload"] >= 1
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["assigned_active_count"], int)
    assert isinstance(data["weighted_load"], int)
    assert isinstance(data["scheduled_minutes"], int)


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["major_code"], str) and data["major_code"]
    assert isinstance(data["cohort_year"], int)
    assert isinstance(data["current_term_code"], str) and data["current_term_code"]
    assert isinstance(data["gpa"], (int, float))
    assert 0.0 <= data["gpa"] <= 4.0
    assert data["care_status"] in ("ENROLLED", "ON_LEAVE", "INACTIVE")
    assert isinstance(data["advising_required_flag"], bool)
    assert isinstance(data["enrolled_term_codes"], list)
    assert isinstance(data["no_show_count"], int)
    assert isinstance(data["at_risk_score"], int)
    assert data["risk_tier"] in ("LOW", "MEDIUM", "HIGH")
    assert data["advising_requirement_status"] in (
        "NOT_REQUIRED",
        "REQUIRED",
        "SATISFIED",
    )
    assert data["registration_clearance"] in ("BLOCKED", "CLEARED")


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["advisor_id"])
    assert data["assignment_mode"] in ("MANUAL", "AUTO")
    assert data["status"] in ("ACTIVE", "ENDED")
    assert data["ended_reason"] in (None, "SUPERSEDED", "MANUAL_END")


def assert_appointment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["advisor_id"])
    assert isinstance(data["term_code"], str) and data["term_code"]
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert isinstance(data["duration_minutes"], int)
    assert data["status"] in (
        "SCHEDULED",
        "CHECKED_IN",
        "COMPLETED",
        "CANCELLED",
        "NO_SHOW",
    )
    assert data["checked_in_at"] is None or is_iso8601_timestamp(data["checked_in_at"])


def assert_drop_in_ticket(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert isinstance(data["reason"], str)
    assert isinstance(data["queue_date"], str) and len(data["queue_date"]) == 10
    assert isinstance(data["position"], int) and data["position"] >= 1
    assert data["status"] in ("QUEUED", "CALLED", "SERVED", "LEFT")
    assert data["called_by_advisor_id"] is None or isinstance(
        data["called_by_advisor_id"], str
    )


def assert_referral(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["source"] in ("FACULTY", "STAFF")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["reason"], str)
    assert data["status"] in (
        "OPEN",
        "OUTREACH_IN_PROGRESS",
        "NO_RESPONSE",
        "RESPONDED",
        "ESCALATED",
        "CLOSED",
    )
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    assert is_iso8601_timestamp(data["due_at"])
    assert isinstance(data["is_sla_breached"], bool)


def assert_intervention(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["referral_id"] is None or isinstance(data["referral_id"], str)
    assert data["intervention_type"] in (
        "ACADEMIC_COACHING",
        "TUTORING_REFERRAL",
        "COUNSELING_REFERRAL",
        "FINANCIAL_AID_REFERRAL",
    )
    assert data["status"] in ("OPEN", "CLOSED")
    assert data["outcome"] in (None, "SUCCESSFUL", "UNSUCCESSFUL")


def assert_hold(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["hold_type"] in (
        "ADVISING",
        "FINANCIAL",
        "ACADEMIC_STANDING",
        "ADMINISTRATIVE",
    )
    assert isinstance(data["requires_approved_plan"], bool)
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_degree_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert isinstance(data["catalog_year"], int)
    assert isinstance(data["required_credits"], int) and data["required_credits"] >= 1
    assert isinstance(data["terms"], list)
    for entry in data["terms"]:
        assert isinstance(entry["term_code"], str) and entry["term_code"]
        assert isinstance(entry["courses"], list)
        for c in entry["courses"]:
            assert isinstance(c["course_code"], str) and c["course_code"]
            assert isinstance(c["credits"], (int, float))
    assert isinstance(data["mapped_credits_total"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED")


def assert_note(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert isinstance(data["author_user_id"], str) and data["author_user_id"]
    assert data["visibility"] in ("SHARED", "CONFIDENTIAL")
    assert isinstance(data["body"], str)


def assert_student_risk_invariants(data: dict):
    """Tier band must agree with the score (PRD §3.2 thresholds)."""
    score = data["at_risk_score"]
    tier = data["risk_tier"]
    if score >= 70:
        assert tier == "HIGH", f"score {score} must be HIGH, got {tier}"
    elif score >= 40:
        assert tier == "MEDIUM", f"score {score} must be MEDIUM, got {tier}"
    else:
        assert tier == "LOW", f"score {score} must be LOW, got {tier}"
    assert 0 <= score <= 100
