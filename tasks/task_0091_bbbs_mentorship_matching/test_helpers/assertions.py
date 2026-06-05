"""Entity assertions and domain invariant checkers (PRD §2.4, §3.1–§3.7)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _assert_common(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int >= 1: {data.get('version')!r}"
    )


def assert_volunteer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["gender"] in ("MALE", "FEMALE", "NONBINARY")
    assert isinstance(data["home_zip"], str)
    assert isinstance(data["interest_tags"], list)
    assert isinstance(data["max_weekly_hours"], int)
    assert data["status"] in (
        "APPLIED", "SCREENING", "ELIGIBLE", "MATCHED", "INACTIVE", "SCREENING_FAILED",
    )
    assert isinstance(data["active_match_count"], int) and data["active_match_count"] >= 0


def assert_background_check(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["volunteer_id"])
    assert data["check_type"] in ("CRIMINAL", "DMV", "CHILD_ABUSE_REGISTRY")
    assert data["status"] in ("PENDING", "CLEARED", "FLAGGED", "EXPIRED")
    assert isinstance(data["adverse_findings"], int)


def assert_guardian(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["consent_on_file"], bool)


def assert_child(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["guardian_id"])
    assert isinstance(data["first_name"], str) and data["first_name"]
    assert isinstance(data["age"], int) and 6 <= data["age"] <= 16
    assert data["gender"] in ("MALE", "FEMALE", "NONBINARY")
    assert isinstance(data["home_zip"], str)
    assert isinstance(data["interest_tags"], list)
    assert isinstance(data["requires_same_gender"], bool)
    assert data["status"] in ("WAITLISTED", "PROPOSED", "MATCHED", "INACTIVE")


def assert_proposal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["child_id"])
    assert is_valid_uuid(data["volunteer_id"])
    assert isinstance(data["compatibility_score"], (int, float))
    assert_cost_precision(float(data["compatibility_score"]))
    assert isinstance(data["candidate_pool_size"], int) and data["candidate_pool_size"] >= 0
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "SUPERSEDED")


def assert_match(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["child_id"])
    assert is_valid_uuid(data["volunteer_id"])
    assert is_valid_uuid(data["proposal_id"])
    assert data["relationship_status"] in (
        "CONFIRMED", "INTRODUCED", "ACTIVE", "CLOSED",
    )
    assert data["compliance_status"] in ("GREEN", "AMBER", "RED")
    assert isinstance(data["total_mentoring_minutes"], int)
    assert data["total_mentoring_minutes"] >= 0


def assert_meeting(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["match_id"])
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in ("SCHEDULED", "HELD", "NO_SHOW", "AFFIRMED", "RESCINDED")


def assert_supervision_contact(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["match_id"])
    assert data["status"] in ("OPEN", "COMPLETED", "MISSED")
    assert isinstance(data["concern_flag"], bool)


def assert_exit_transition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["match_id"])
    assert data["exit_type"] in ("SUCCESSFUL_CLOSURE", "EARLY_TERMINATION")
    assert data["initiated_by"] in ("BIG", "LITTLE", "GUARDIAN", "AGENCY")
    assert data["reason_code"] in (
        "GRADUATION", "RELOCATION", "LOST_INTEREST", "SAFETY_CONCERN", "PROGRAM_VIOLATION",
    )
    assert data["status"] in ("DRAFT", "FINALIZED")
    assert isinstance(data["survey_required"], bool)


def assert_outcome_survey(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["match_id"])
    assert is_valid_uuid(data["exit_transition_id"])
    assert 1 <= data["relationship_quality"] <= 5
    assert 1 <= data["child_outcome"] <= 5
    assert isinstance(data["would_rematch"], bool)
    assert isinstance(data["composite_score"], (int, float))
    assert_cost_precision(float(data["composite_score"]))
    assert data["outcome_band"] in ("STRONG", "MODERATE", "WEAK")


def assert_activity_log(data: dict):
    """Append-only entry — carries ONLY id + created_at, no updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["match_id"])
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 1
    assert data["activity_type"] in ("OUTING", "CALL", "MEAL", "TUTORING", "EVENT")
    assert data["status"] == "LOGGED"
