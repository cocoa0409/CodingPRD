"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)

TERM_STATUSES = ["DRAFT", "OPEN", "LOCKED", "PUBLISHED"]
FACULTY_STATUSES = ["ACTIVE", "ON_LEAVE", "SEPARATED"]
FACULTY_RANKS = [
    "ADJUNCT", "LECTURER", "ASSISTANT_PROFESSOR", "ASSOCIATE_PROFESSOR", "PROFESSOR",
]
COURSE_TYPES = ["LECTURE", "LAB", "SEMINAR"]
MODALITIES = ["IN_PERSON", "ONLINE", "HYBRID"]
MEETING_DAYS = ["MON", "TUE", "WED", "THU", "FRI"]
QUALIFICATION_STATUSES = ["ACTIVE", "REVOKED", "EXPIRED"]
SECTION_STATUSES = ["PROPOSED", "SCHEDULED", "STAFFED", "CANCELLED"]
ASSIGNMENT_STATUSES = [
    "PROPOSED", "CONFIRMED", "DECLINED", "WITHDRAWN", "RESCINDED", "CANCELLED",
]
GRANT_TYPES = ["RESEARCH_BUYOUT", "ADMINISTRATIVE", "SABBATICAL"]
GRANT_STATUSES = ["REQUESTED", "APPROVED", "DENIED", "REVOKED"]
OVERLOAD_STATUSES = ["SUBMITTED", "CHAIR_ENDORSED", "DEAN_APPROVED", "DENIED", "WITHDRAWN"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_workload_term(data: dict):
    _assert_common(data)
    assert isinstance(data["term_code"], str) and len(data["term_code"]) > 0
    assert isinstance(data["title"], str)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["census_date"], str)
    assert isinstance(data["comp_budget_cents"], int)
    assert isinstance(data["comp_budget_spent_cents"], int)
    assert data["comp_budget_spent_cents"] >= 0
    assert data["comp_budget_spent_cents"] <= data["comp_budget_cents"]
    assert isinstance(data["lecture_multiplier"], (int, float))
    assert isinstance(data["lab_multiplier"], (int, float))
    assert isinstance(data["seminar_multiplier"], (int, float))
    assert isinstance(data["online_premium_credits"], (int, float))
    assert isinstance(data["large_class_threshold"], int)
    assert isinstance(data["large_class_bonus_credits"], (int, float))
    assert isinstance(data["overload_comp_rate_cents"], int)
    assert isinstance(data["union_max_overload_credits"], (int, float))
    assert isinstance(data["reassignment_notice_days"], int)
    assert isinstance(data["late_cancel_stipend_cents"], int)
    assert isinstance(data["flat_release_rate_cents"], int)
    assert data["status"] in TERM_STATUSES


def assert_faculty_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["rank"] in FACULTY_RANKS
    assert isinstance(data["is_union_covered"], bool)
    assert isinstance(data["base_load_credits"], (int, float))
    assert isinstance(data["base_salary_cents"], int)
    assert isinstance(data["preferred_course_ids"], list)
    assert data["status"] in FACULTY_STATUSES


def assert_course(data: dict):
    _assert_common(data)
    assert isinstance(data["course_code"], str) and len(data["course_code"]) > 0
    assert isinstance(data["title"], str)
    assert data["course_type"] in COURSE_TYPES
    assert isinstance(data["base_credits"], (int, float))
    assert isinstance(data["default_enrollment_cap"], int)
    assert isinstance(data["allowed_modalities"], list) and len(data["allowed_modalities"]) > 0
    for m in data["allowed_modalities"]:
        assert m in MODALITIES


def assert_qualification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("faculty_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["expires_on"], str)
    assert data["status"] in QUALIFICATION_STATUSES


def assert_course_section(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("term_id", ""))
    assert is_valid_uuid(data.get("course_id", ""))
    assert isinstance(data["section_number"], str)
    assert data["modality"] in MODALITIES
    assert data["meeting_day"] in MEETING_DAYS
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["end_minute"], int)
    assert 0 <= data["start_minute"] <= 1439
    assert 0 <= data["end_minute"] <= 1439
    assert data["end_minute"] > data["start_minute"]
    assert isinstance(data["enrollment_cap"], int)
    assert isinstance(data["enrolled_count"], int)
    assert 0 <= data["enrolled_count"] <= data["enrollment_cap"]
    assert isinstance(data["is_late_cancelled"], bool)
    assert data["status"] in SECTION_STATUSES


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("term_id", ""))
    assert is_valid_uuid(data.get("section_id", ""))
    assert is_valid_uuid(data.get("faculty_id", ""))
    assert isinstance(data["credit_units"], (int, float))
    assert_cost_precision(data["credit_units"])
    assert data["final_credit_units"] is None or isinstance(
        data["final_credit_units"], (int, float)
    )
    if data["final_credit_units"] is not None:
        assert_cost_precision(data["final_credit_units"])
    assert isinstance(data["stipend_cents"], int) and data["stipend_cents"] >= 0
    assert isinstance(data["matches_preference"], bool)
    assert data["status"] in ASSIGNMENT_STATUSES


def assert_release_time_grant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("term_id", ""))
    assert is_valid_uuid(data.get("faculty_id", ""))
    assert data["grant_type"] in GRANT_TYPES
    assert isinstance(data["credits_released"], (int, float))
    assert data["credits_released"] > 0
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert data["end_date"] >= data["start_date"]
    assert data["buyout_value_cents"] is None or isinstance(data["buyout_value_cents"], int)
    assert data["status"] in GRANT_STATUSES


def assert_overload_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("term_id", ""))
    assert is_valid_uuid(data.get("faculty_id", ""))
    assert isinstance(data["overload_credits"], (int, float))
    assert data["overload_credits"] > 0
    assert isinstance(data["comp_cents"], int) and data["comp_cents"] >= 0
    assert data["status"] in OVERLOAD_STATUSES


def assert_load_sheet(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("term_id", ""))
    assert is_valid_uuid(data.get("faculty_id", ""))
    for field in (
        "teaching_credits",
        "release_credits",
        "effective_obligation_credits",
        "overload_credits",
        "underload_credits",
    ):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"
        assert data[field] >= 0, f"{field} must be >= 0"
        assert_cost_precision(data[field])


def assert_load_sheet_invariants(data: dict, base_load_credits):
    """Domain invariants that must hold for any load sheet."""
    expected_obligation = max(0.0, base_load_credits - data["release_credits"])
    assert data["effective_obligation_credits"] == pytest.approx(expected_obligation, abs=0.005), (
        f"effective_obligation_credits {data['effective_obligation_credits']} != "
        f"max(0, {base_load_credits} - {data['release_credits']})"
    )
    expected_overload = max(0.0, data["teaching_credits"] - data["effective_obligation_credits"])
    assert data["overload_credits"] == pytest.approx(expected_overload, abs=0.005), (
        f"overload_credits {data['overload_credits']} != "
        f"max(0, {data['teaching_credits']} - {data['effective_obligation_credits']})"
    )
    expected_underload = max(0.0, data["effective_obligation_credits"] - data["teaching_credits"])
    assert data["underload_credits"] == pytest.approx(expected_underload, abs=0.005), (
        f"underload_credits {data['underload_credits']} != "
        f"max(0, {data['effective_obligation_credits']} - {data['teaching_credits']})"
    )
