"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response shape against the PRD contract
using the framework's generic format checkers. Domain invariant checkers encode
cross-field rules that must hold after any operation (e.g. visit-pool
conservation, §2.6).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system-managed fields (PRD §2.4) for first-class entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_child(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["date_of_birth"], str) and len(data["date_of_birth"]) > 0
    assert isinstance(data["age_months_at_intake"], int)
    assert data["coordination_program"] in ("NONE", "EARLY_INTERVENTION", "SCHOOL")
    assert isinstance(data["active_appointment_count"], int)
    assert data["status"] in ("ACTIVE", "DISCHARGED")


def assert_therapist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["discipline"] in ("SLP", "OT")
    assert isinstance(data["max_caseload"], int) and data["max_caseload"] >= 1
    assert isinstance(data["weekly_visit_minutes_cap"], int) and data["weekly_visit_minutes_cap"] >= 0
    assert isinstance(data["current_caseload"], int) and data["current_caseload"] >= 0
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_evaluation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("child_id", "")), "child_id must be a UUID"
    assert data["discipline"] in ("SLP", "OT")
    assert isinstance(data["severity_score"], int) and 0 <= data["severity_score"] <= 100
    assert data["status"] in ("DRAFT", "FINALIZED", "SUPERSEDED")


def assert_plan_of_care(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("child_id", ""))
    assert is_valid_uuid(data.get("evaluation_id", ""))
    assert is_valid_uuid(data.get("primary_therapist_id", ""))
    assert data["discipline"] in ("SLP", "OT")
    assert isinstance(data["planned_weekly_minutes"], int) and data["planned_weekly_minutes"] >= 0
    assert isinstance(data["goal_count"], int) and data["goal_count"] >= 0
    assert isinstance(data["overall_progress_pct"], (int, float))
    assert data["status"] in ("DRAFT", "ACTIVE", "ON_HOLD", "DISCHARGED")


def assert_goal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("plan_of_care_id", ""))
    assert isinstance(data["description"], str)
    assert isinstance(data["weight"], int) and data["weight"] >= 1
    assert isinstance(data["baseline_pct"], int) and 0 <= data["baseline_pct"] <= 100
    assert isinstance(data["target_pct"], int) and 0 <= data["target_pct"] <= 100
    assert isinstance(data["latest_progress_pct"], int) and 0 <= data["latest_progress_pct"] <= 100
    assert data["status"] in ("OPEN", "MET", "DISCONTINUED")


def assert_authorization(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("child_id", ""))
    assert data["discipline"] in ("SLP", "OT")
    assert isinstance(data["payer_name"], str)
    assert isinstance(data["authorized_visits"], int) and data["authorized_visits"] >= 1
    assert isinstance(data["reserved_visits"], int) and data["reserved_visits"] >= 0
    assert isinstance(data["committed_visits"], int) and data["committed_visits"] >= 0
    assert isinstance(data["available_visits"], int)
    assert data["status"] in ("ACTIVE", "REAUTH_REQUESTED", "EXHAUSTED", "EXPIRED", "CLOSED")
    assert_visit_pool_invariants(data)


def assert_visit_pool_invariants(auth: dict):
    """PRD §2.6: available_visits == authorized_visits - reserved_visits -
    committed_visits, and all counts are exact integers."""
    assert auth["available_visits"] == (
        auth["authorized_visits"] - auth["reserved_visits"] - auth["committed_visits"]
    ), "available_visits must equal authorized - reserved - committed"


def assert_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("child_id", ""))
    assert is_valid_uuid(data.get("therapist_id", ""))
    assert is_valid_uuid(data.get("authorization_id", ""))
    assert is_valid_uuid(data.get("plan_of_care_id", ""))
    assert isinstance(data["start_time"], str)
    assert isinstance(data["end_time"], str)
    assert isinstance(data["duration_minutes"], int)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW")


def assert_session_note(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("appointment_id", ""))
    assert isinstance(data["narrative"], str)
    assert isinstance(data["minutes_delivered"], int) and data["minutes_delivered"] >= 1


def assert_coordination_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("child_id", ""))
    assert data["plan_type"] in ("IFSP", "IEP")
    assert isinstance(data["jurisdiction"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "TRANSITIONING", "CLOSED")


def assert_home_program(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("plan_of_care_id", ""))
    assert isinstance(data["title"], str)
    assert isinstance(data["weekly_target_sessions"], int) and data["weekly_target_sessions"] >= 1
    assert isinstance(data["parent_training_completed"], bool)
    assert data["status"] in ("ASSIGNED", "ACTIVE", "COMPLETED", "CANCELLED")


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("child_id", ""))
    assert is_valid_uuid(data.get("therapist_id", ""))
    assert data["discipline"] in ("SLP", "OT")
    assert is_valid_uuid(data.get("evaluation_id", ""))
    assert isinstance(data["priority_score"], int)
    assert isinstance(data["requested_minutes"], int) and data["requested_minutes"] >= 1
    assert data["status"] in ("WAITING", "OFFERED", "PLACED", "EXPIRED", "WITHDRAWN")


def assert_goal_progress_entry(data: dict):
    """PRD §2.4: a goal progress entry is an append-only event-log record — it
    carries only id and created_at and has NO updated_at and NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "goal progress entry must not expose updated_at"
    assert "version" not in data, "goal progress entry must not expose version"
    assert isinstance(data["recorded_pct"], int) and 0 <= data["recorded_pct"] <= 100
