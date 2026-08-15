"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_immutable_fields(data: dict, entity: str):
    """PRD §2.5: immutable records carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_program(data: dict):
    _assert_common_fields(data, "Program")
    assert isinstance(data["name"], str) and data["name"]
    assert data["focus_area"] in ["GRIEF", "ADDICTION", "ANXIETY", "PARENTING", "CHRONIC_ILLNESS"]
    assert data["posture"] in ["OPEN", "CAUTION", "LOCKDOWN"]
    assert isinstance(data["active_critical_incident_count"], int)
    assert isinstance(data["active_standard_incident_count"], int)
    assert isinstance(data["scheduled_session_count"], int)


def assert_peer_group(data: dict):
    _assert_common_fields(data, "PeerGroup")
    assert isinstance(data["name"], str) and data["name"]
    assert data["modality"] in ["IN_PERSON", "VIRTUAL", "HYBRID"]
    assert isinstance(data["base_capacity"], int) and data["base_capacity"] >= 1
    assert 1 <= data["required_facilitator_level"] <= 5
    assert data["status"] in ["DRAFT", "ACTIVE", "PAUSED", "RETIRED"]
    assert isinstance(data["active_enrollment_count"], int)


def assert_session(data: dict):
    _assert_common_fields(data, "Session")
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert is_valid_uuid(data["primary_facilitator_id"])
    assert data["status"] in [
        "DRAFT", "SCHEDULED", "IN_PROGRESS", "COMPLETED",
        "COMPLETED_WITH_INCIDENT", "CANCELLED",
    ]
    assert isinstance(data["reserved_seats"], int)
    assert isinstance(data["confirmed_seats"], int)
    assert isinstance(data["effective_capacity"], int)


def assert_room(data: dict):
    _assert_common_fields(data, "Room")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["physical_capacity"], int) and data["physical_capacity"] >= 1
    assert data["status"] in ["AVAILABLE", "OUT_OF_SERVICE"]


def assert_facilitator(data: dict):
    _assert_common_fields(data, "Facilitator")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["status"] in [
        "APPLIED", "SCREENING", "IN_TRAINING", "SUPERVISED_PRACTICE",
        "CERTIFIED", "SUSPENDED", "WITHDRAWN", "REJECTED",
    ]
    assert 1 <= data["level"] <= 5
    assert isinstance(data["supervision_required"], bool)
    assert is_iso8601_timestamp(data["application_submitted_at"])


def assert_training_course(data: dict):
    _assert_common_fields(data, "TrainingCourse")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["credit_hours"], int) and data["credit_hours"] >= 1
    assert 1 <= data["level_weight"] <= 3
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_training_completion(data: dict):
    _assert_common_fields(data, "TrainingCompletion")
    assert is_valid_uuid(data["facilitator_id"])
    assert is_valid_uuid(data["course_id"])
    assert is_iso8601_timestamp(data["completed_at"])
    assert 0 <= data["score"] <= 100


def assert_supervision_review(data: dict):
    _assert_common_fields(data, "SupervisionReview")
    assert is_valid_uuid(data["facilitator_id"])
    assert is_valid_uuid(data["reviewer_id"])
    assert is_iso8601_timestamp(data["occurred_at"])
    assert 1 <= data["rating"] <= 5


def assert_participant(data: dict):
    _assert_common_fields(data, "Participant")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert 1 <= data["household_size"] <= 8
    assert data["status"] in ["REGISTERED", "ACTIVE", "SUSPENDED", "DEACTIVATED"]
    assert isinstance(data["attendance_streak"], int)
    assert isinstance(data["total_no_shows"], int)


def assert_confidentiality_agreement(data: dict):
    _assert_immutable_fields(data, "ConfidentialityAgreement")
    assert is_iso8601_timestamp(data["signed_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in ["SIGNED", "EXPIRED", "REVOKED"]
    assert isinstance(data["agreement_version"], int)


def assert_enrollment(data: dict):
    _assert_common_fields(data, "Enrollment")
    assert is_valid_uuid(data["group_id"])
    assert is_valid_uuid(data["participant_id"])
    assert data["seat_status"] in ["RESERVED", "CONFIRMED", "WAITLISTED", "RELEASED", "CANCELLED"]
    assert data["agreement_status"] in ["PENDING", "SIGNED", "EXPIRED", "REVOKED"]
    assert is_iso8601_timestamp(data["reserved_at"])


def assert_attendance_record(data: dict):
    _assert_common_fields(data, "AttendanceRecord")
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["participant_id"])
    assert is_iso8601_timestamp(data["check_in_at"])
    assert data["access_modality"] in ["IN_PERSON", "VIRTUAL"]
    assert data["status"] in ["CHECKED_IN", "ATTENDED", "NO_SHOW", "VOIDED"]


def assert_incident_report(data: dict):
    _assert_common_fields(data, "IncidentReport")
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["raised_by_facilitator_id"])
    assert data["severity"] in ["STANDARD", "CRITICAL"]
    assert data["category"] in ["SAFETY", "CONFIDENTIALITY", "HARASSMENT", "MEDICAL", "OTHER"]
    assert data["status"] in ["OPEN", "ACKNOWLEDGED", "RESOLVED", "ESCALATED_TO_CLINICAL"]


def assert_clinical_referral(data: dict):
    _assert_common_fields(data, "ClinicalReferral")
    assert is_valid_uuid(data["participant_id"])
    assert data["reason_code"] in ["OUT_OF_SCOPE", "CRISIS", "MEDICAL", "RISK_OF_HARM"]
    assert data["status"] in ["PENDING", "ACCEPTED", "DECLINED", "COMPLETED"]


def assert_evaluation_survey(data: dict):
    _assert_immutable_fields(data, "EvaluationSurvey")
    assert is_valid_uuid(data["session_id"])
    assert is_valid_uuid(data["participant_id"])
    for field in ("overall_rating", "facilitator_rating", "modality_rating"):
        assert 1 <= data[field] <= 5, f"{field} must be in 1..5"
    assert is_iso8601_timestamp(data["submitted_at"])
