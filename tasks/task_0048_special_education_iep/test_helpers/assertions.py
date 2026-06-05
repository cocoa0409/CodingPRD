"""Entity assertions and domain invariant checkers (PRD §3).

Each assert_{entity}() verifies the shape and field domains the PRD promises
on a fetched/created resource. Generic UUID and timestamp validators come from
the framework.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_student(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_iso8601_timestamp(data["date_of_birth"]) or isinstance(data["date_of_birth"], str)
    assert isinstance(data["grade_level"], int) and 0 <= data["grade_level"] <= 12
    assert data["eligibility_status"] in ("NOT_EVALUATED", "ELIGIBLE", "INELIGIBLE")
    assert data["disability_category"] in (
        None, "SLD", "AUTISM", "SPEECH_LANGUAGE", "OHI", "EMOTIONAL", "INTELLECTUAL",
    )
    assert data["active_iep_id"] is None or is_valid_uuid(data["active_iep_id"])
    assert data["next_reeval_due_date"] is None or isinstance(data["next_reeval_due_date"], str)


def assert_evaluation(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["eval_type"] in ("INITIAL", "TRIENNIAL")
    assert data["proposed_category"] in (
        "SLD", "AUTISM", "SPEECH_LANGUAGE", "OHI", "EMOTIONAL", "INTELLECTUAL",
    )
    assert data["status"] in ("REQUESTED", "CONSENT_PENDING", "IN_PROGRESS", "FINALIZED")
    assert data["outcome"] in (None, "ELIGIBLE", "INELIGIBLE")


def assert_iep(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert isinstance(data["school_day_minutes"], int) and data["school_day_minutes"] > 0
    assert data["status"] in ("DRAFT", "MEETING_HELD", "ACTIVE", "AMENDMENT_PENDING", "ARCHIVED")
    assert isinstance(data["lre_general_ed_pct"], (int, float))
    assert data["lre_setting"] in ("FULL_INCLUSION", "RESOURCE", "SEPARATE_CLASS")


def assert_goal(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["iep_id"])
    assert data["domain"] in ("READING", "MATH", "WRITING", "COMMUNICATION", "BEHAVIOR", "MOTOR")
    assert isinstance(data["baseline_value"], (int, float))
    assert isinstance(data["target_value"], (int, float))
    assert data["target_value"] > data["baseline_value"]
    assert data["status"] in ("ACTIVE", "MET", "DISCONTINUED")
    assert isinstance(data["latest_progress_pct"], (int, float))
    assert isinstance(data["cumulative_progress_pct"], (int, float))


def assert_progress_report(data: dict):
    """ProgressReport is immutable (PRD §2.4): only id + created_at, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["goal_id"])
    assert isinstance(data["reporting_period"], int)


def assert_progress_report_is_immutable(data: dict):
    """Per PRD §2.4 a progress report carries no `version` and no `updated_at`."""
    assert "version" not in data, "ProgressReport must NOT carry a version field (PRD §2.4)"
    assert "updated_at" not in data, "ProgressReport must NOT carry an updated_at field (PRD §2.4)"


def assert_related_service(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["iep_id"])
    assert data["service_type"] in ("OT", "PT", "SPEECH")
    assert isinstance(data["minutes_per_week"], int) and data["minutes_per_week"] > 0
    assert isinstance(data["delivered_in_general_ed"], bool)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_consent_request(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["student_id"])
    assert data["iep_id"] is None or is_valid_uuid(data["iep_id"])
    assert data["consent_type"] in ("EVALUATION", "PLACEMENT")
    assert data["status"] in ("PENDING", "GRANTED", "DENIED", "REVOKED")
    assert data["decided_at"] is None or isinstance(data["decided_at"], str)


def assert_transition_plan(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["iep_id"])
    assert isinstance(data["postsecondary_goal"], str)
    assert isinstance(data["services_summary"], str)
    assert data["status"] in ("DRAFT", "ADOPTED")
