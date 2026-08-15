"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert data["degree_type"] in ("ASSOCIATE", "BACHELOR", "MASTER")
    assert isinstance(data["min_total_credits"], (int, float))
    assert isinstance(data["min_gpa"], (int, float))
    assert data["catalog_year_end"] > data["catalog_year_start"]
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_requirement_group(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["group_code"], str) and data["group_code"]
    assert isinstance(data["required_credits"], (int, float))
    assert data["min_grade"] in ("A", "B", "C", "D")
    assert isinstance(data["eligible_course_codes"], list)


def assert_honors_policy(data: dict):
    _assert_common_fields(data)
    assert data["honors_gpa_basis"] in ("INSTITUTIONAL", "CUMULATIVE")
    for field in ("cum_threshold", "magna_threshold", "summa_threshold"):
        assert isinstance(data[field], (int, float))
    assert data["effective_last_year"] >= data["effective_first_year"]
    assert isinstance(data["residency_min_credits"], int)


def assert_course(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert isinstance(data["credits"], (int, float)) and data["credits"] > 0


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_number"], str) and data["student_number"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["financial_hold"], bool)
    assert data["status"] in ("ACTIVE", "GRADUATED")
    for field in ("total_earned_credits", "institutional_earned_credits"):
        assert isinstance(data[field], (int, float)) and data[field] >= 0
    for field in ("institutional_gpa", "cumulative_gpa"):
        assert isinstance(data[field], (int, float))
        assert 0.0 <= data[field] <= 4.0


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a UUID"
    assert is_valid_uuid(data.get("course_id", "")), "course_id must be a UUID"
    assert isinstance(data["term"], str) and data["term"]
    assert isinstance(data["is_transfer"], bool)
    assert data["status"] in ("IN_PROGRESS", "COMPLETED", "WITHDRAWN")
    assert data["grade"] in ("A", "B", "C", "D", "F", "W", None)
    assert isinstance(data["credits_attempted"], (int, float))
    assert isinstance(data["credits_earned"], (int, float))
    assert isinstance(data["grade_points"], (int, float))


def assert_student_program(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a UUID"
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data["catalog_year"], int)
    assert data["status"] in ("ACTIVE", "WITHDRAWN", "COMPLETED")
    assert isinstance(data["latest_audit_satisfied"], bool)


def assert_degree_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("student_program_id", "")), "student_program_id must be a UUID"
    assert data["audit_kind"] in ("STANDARD", "WHAT_IF", "CONDITIONAL", "FINAL")
    assert data["status"] in ("CURRENT", "SUPERSEDED")
    assert isinstance(data["catalog_year_used"], int)
    assert isinstance(data["total_credits_applied"], (int, float))
    assert isinstance(data["in_progress_credits_counted"], (int, float))
    assert isinstance(data["outstanding_credits"], (int, float))
    assert isinstance(data["gpa_at_audit"], (int, float))
    assert isinstance(data["overall_satisfied"], bool)
    assert isinstance(data["groups_result"], list)
    for group in data["groups_result"]:
        assert is_valid_uuid(group.get("requirement_group_id", ""))
        assert isinstance(group["group_code"], str)
        assert isinstance(group["credits_applied"], (int, float))
        assert isinstance(group["effective_required_credits"], (int, float))
        assert isinstance(group["satisfied"], bool)


def assert_substitution_waiver(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("student_program_id", "")), "student_program_id must be a UUID"
    assert is_valid_uuid(data.get("requirement_group_id", "")), "requirement_group_id must be a UUID"
    assert data["kind"] in ("SUBSTITUTION", "WAIVER")
    assert data["requested_by_role"] in ("STUDENT", "ADVISOR")
    assert isinstance(data["requested_by_user_id"], str) and data["requested_by_user_id"]
    assert data["status"] in ("SUBMITTED", "ADVISOR_APPROVED", "APPROVED", "DENIED", "REVOKED")


def assert_graduation_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("student_program_id", "")), "student_program_id must be a UUID"
    assert isinstance(data["expected_term"], str) and data["expected_term"]
    assert isinstance(data["expected_conferral_date"], str) and data["expected_conferral_date"]
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "CLEARED",
        "CONDITIONALLY_CLEARED", "DENIED", "DEGREE_CONFERRED",
    )
    assert data.get("honors_designation") in (
        None, "NONE", "CUM_LAUDE", "MAGNA_CUM_LAUDE", "SUMMA_CUM_LAUDE",
    )


def assert_diploma(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert isinstance(data["printed_name"], str) and data["printed_name"]
    assert isinstance(data["conferral_date"], str) and data["conferral_date"]
    assert data["honors_designation"] in ("NONE", "CUM_LAUDE", "MAGNA_CUM_LAUDE", "SUMMA_CUM_LAUDE")
    assert data["status"] in ("PENDING", "ISSUED", "REVOKED")


def assert_gpa(value, expected: float):
    """GPA comparisons: 3-decimal round-half-up values (PRD §2.9)."""
    assert float(value) == pytest.approx(expected, abs=1e-6), (
        f"Expected GPA {expected}, got {value}"
    )
