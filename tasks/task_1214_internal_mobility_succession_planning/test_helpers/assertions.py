"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

import pytest

from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits) into
    an aware datetime, so instant comparisons are serialization-agnostic."""
    assert is_iso8601_timestamp(value), f"Not a valid ISO 8601 timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_instant_equals(value: str, expected: str):
    """Assert two ISO 8601 timestamps denote the same instant."""
    assert parse_timestamp(value) == parse_timestamp(expected), (
        f"Expected instant {expected}, got {value}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_employee(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["employee_code"], str) and data["employee_code"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["department"], str) and data["department"]
    assert isinstance(data["job_level"], int) and 1 <= data["job_level"] <= 10
    assert isinstance(data["hire_date"], str) and len(data["hire_date"]) == 10
    assert data["demographic_group"] in [
        "GROUP_A", "GROUP_B", "GROUP_C", "GROUP_D", "UNDISCLOSED",
    ]
    assert data["performance_rating"] in ["LOW", "SOLID", "STRONG", "EXCEPTIONAL"]
    assert isinstance(data["rating_history"], list)
    assert data["employment_status"] in ["ACTIVE", "TERMINATED"]
    assert isinstance(data["is_high_potential"], bool)
    assert isinstance(data["active_hold_count"], int) and data["active_hold_count"] >= 0


def assert_critical_role(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["role_title"], str) and data["role_title"]
    assert isinstance(data["department"], str) and data["department"]
    assert data["criticality_tier"] in ["TIER_1", "TIER_2", "TIER_3"]
    assert data["assessment_method"] in ["WEIGHTED", "COVERAGE"]
    assert data["status"] in ["PROPOSED", "ACTIVE", "VACANT", "RETIRED"]
    assert isinstance(data["bench_strength"], (int, float))
    assert 0 <= float(data["bench_strength"]) <= 100
    assert_cost_precision(float(data["bench_strength"]), 2)
    assert data["bench_posture"] in ["EMPTY", "THIN", "ADEQUATE", "STRONG"]
    assert isinstance(data["posture_alert"], bool)


def assert_successor_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("critical_role_id", "")), "critical_role_id must be a UUID"
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a UUID"
    assert data["readiness_rating"] in ["READY_NOW", "READY_1_2", "READY_3_PLUS"]
    assert isinstance(data["slate_position"], int) and 1 <= data["slate_position"] <= 5
    assert isinstance(data["readiness_score"], (int, float))
    assert 0 <= float(data["readiness_score"]) <= 100
    assert_cost_precision(float(data["readiness_score"]), 2)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "REMOVED", "PROMOTED"]


def assert_development_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("successor_entry_id", "")), "successor_entry_id must be a UUID"
    assert data["target_readiness"] in ["READY_NOW", "READY_1_2", "READY_3_PLUS"]
    assert isinstance(data["completion_pct"], int) and 0 <= data["completion_pct"] <= 100
    assert data["status"] in ["DRAFT", "ACTIVE", "COMPLETED", "ABANDONED"]


def assert_vacancy(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("critical_role_id", "")), "critical_role_id must be a UUID"
    assert data["status"] in ["OPEN", "FILLED", "CLOSED_UNFILLED"]
    assert is_iso8601_timestamp(data.get("fill_deadline", "")), "fill_deadline must be ISO 8601"
    if data["status"] == "FILLED":
        assert data["fill_source"] in ["SUCCESSION_SLATE", "INTERNAL_POSTING"]
        assert is_valid_uuid(data.get("filled_by_employee_id", ""))


def assert_posting(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("vacancy_id", "")), "vacancy_id must be a UUID"
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["min_tenure_months"], int)
    assert isinstance(data["min_job_level"], int)
    assert data["planned_open_date"] <= data["planned_close_date"]
    assert data["status"] in ["DRAFT", "OPEN", "CLOSED", "CANCELLED"]
    assert isinstance(data["application_count"], int) and data["application_count"] >= 0


def assert_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("posting_id", "")), "posting_id must be a UUID"
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a UUID"
    assert is_iso8601_timestamp(data.get("submitted_at", "")), "submitted_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("consent_deadline", "")), "consent_deadline must be ISO 8601"
    assert data["status"] in [
        "PENDING_MANAGER_CONSENT", "MANAGER_HOLD", "CONSENT_GRANTED",
        "INTERVIEWING", "OFFER_EXTENDED", "OFFER_ACCEPTED", "OFFER_DECLINED",
        "REJECTED", "WITHDRAWN",
    ]


def assert_calibration_session(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["department_scope"], str) and data["department_scope"]
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "FINALIZED"]
    assert isinstance(data["entry_count"], int) and data["entry_count"] >= 0
    assert isinstance(data["ratified_count"], int) and 0 <= data["ratified_count"] <= data["entry_count"]


def assert_calibration_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("session_id", "")), "session_id must be a UUID"
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a UUID"
    assert data["proposed_rating"] in ["LOW", "SOLID", "STRONG", "EXCEPTIONAL"]
    assert isinstance(data["challenge_count"], int) and data["challenge_count"] >= 0
    assert data["status"] in ["PROPOSED", "CHALLENGED", "RATIFIED", "APPLIED"]
    if data["status"] in ["RATIFIED", "APPLIED"]:
        assert data["calibrated_rating"] in ["LOW", "SOLID", "STRONG", "EXCEPTIONAL"]


def assert_hipo_cycle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["cycle_name"], str) and data["cycle_name"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and 0 <= data["enrolled_count"] <= data["capacity"]
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_nomination(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a UUID"
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a UUID"
    assert isinstance(data["review_count"], int) and data["review_count"] >= 0
    assert data["status"] in [
        "NOMINATED", "ENDORSED", "ACTIVE", "UNDER_REVIEW",
        "REMOVED", "REJECTED", "GRADUATED",
    ]


def assert_retention_assessment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("employee_id", "")), "employee_id must be a UUID"
    assert data["assessment_method"] in ["POINT_IN_TIME", "TREND"]
    assert data["trigger_source"] in ["MANUAL", "BENCH_THIN_AUTO"]
    assert isinstance(data["risk_score"], (int, float))
    assert 0 <= float(data["risk_score"]) <= 100
    assert_cost_precision(float(data["risk_score"]), 1)
    assert data["risk_level"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    assert data["status"] in ["OPEN", "ACTION_PLANNED", "ESCALATED", "MITIGATED", "DISMISSED"]


def assert_diversity_snapshot(data: dict):
    """Append-only record: id + created_at present; updated_at/version absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "DiversitySnapshot must not carry updated_at"
    assert "version" not in data, "DiversitySnapshot must not carry version"
    assert data["scope_type"] in ["DEPARTMENT", "HIPO_CYCLE"]
    assert isinstance(data["scope_ref"], str)
    assert isinstance(data["total_subjects"], int) and data["total_subjects"] >= 0
    assert isinstance(data["underrepresented_count"], int)
    assert 0 <= data["underrepresented_count"] <= data["total_subjects"]
    if data["total_subjects"] == 0:
        assert data["diversity_index"] is None
    else:
        assert isinstance(data["diversity_index"], (int, float))
        assert_cost_precision(float(data["diversity_index"]), 2)


def assert_posture_matches_strength(data: dict):
    """bench_posture must be the band of the stored bench_strength."""
    strength = float(data["bench_strength"])
    posture = data["bench_posture"]
    if strength == 0:
        expected = "EMPTY"
    elif strength < 40:
        expected = "THIN"
    elif strength < 70:
        expected = "ADEQUATE"
    else:
        expected = "STRONG"
    assert posture == expected, (
        f"bench_posture {posture} inconsistent with bench_strength {strength} "
        f"(expected {expected})"
    )


def assert_risk_level_matches_score(data: dict):
    """risk_level must be the band of the stored risk_score."""
    score = float(data["risk_score"])
    level = data["risk_level"]
    if score < 30:
        expected = "LOW"
    elif score < 60:
        expected = "MEDIUM"
    elif score < 85:
        expected = "HIGH"
    else:
        expected = "CRITICAL"
    assert level == expected, (
        f"risk_level {level} inconsistent with risk_score {score} (expected {expected})"
    )
