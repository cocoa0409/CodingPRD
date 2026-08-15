"""Entity assertions and domain invariant checkers.

Shape checks for every resource the API returns, built on the framework's
generic validators. DecisionRecord is the append-only exception: it carries
id and created_at but never updated_at or version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_department(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["dept_name"], str) and data["dept_name"]
    assert isinstance(data["subject_codes"], list)
    assert all(isinstance(code, str) for code in data["subject_codes"])
    assert isinstance(data["college"], str) and data["college"]


def assert_term(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["term_code"], str) and data["term_code"]
    assert isinstance(data["academic_year"], str) and data["academic_year"]
    assert isinstance(data["sequence_index"], int)
    assert isinstance(data["classes_start_date"], str)
    assert isinstance(data["classes_end_date"], str)
    assert isinstance(data["proposal_freeze_at"], str)
    assert isinstance(data["catalog_freeze_at"], str)
    assert isinstance(data["scheduled_proposal_count"], int)
    assert data["scheduled_proposal_count"] >= 0
    assert data["status"] in (
        "OPEN_FOR_PROPOSALS", "PROPOSAL_FROZEN", "CATALOG_FROZEN",
    )


def assert_course(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["subject_code"], str) and data["subject_code"]
    assert isinstance(data["course_number"], str) and data["course_number"]
    assert isinstance(data["title"], str)
    assert isinstance(data["credit_hours"], (int, float))
    assert isinstance(data["contact_hours_per_week"], (int, float))
    assert isinstance(data["out_of_class_hours_per_week"], (int, float))
    assert isinstance(data["learning_outcomes"], list)
    assert is_valid_uuid(data["owning_department_id"])
    assert is_valid_uuid(data["introduced_in_term_id"])
    assert isinstance(data["prerequisite_summary"], str)
    assert data.get("last_published_edition_id") is None or is_valid_uuid(
        data["last_published_edition_id"]
    )
    assert data["status"] in ("ACTIVE", "DEACTIVATING", "INACTIVE")


def assert_proposal(data: dict):
    _assert_common_fields(data)
    assert data["proposal_type"] in ("NEW_COURSE", "COURSE_CHANGE", "DEACTIVATION")
    assert isinstance(data["proposer_id"], str) and data["proposer_id"]
    assert is_valid_uuid(data["proposer_department_id"])
    assert is_valid_uuid(data["requested_effective_term_id"])
    assert data["status"] in (
        "DRAFT", "DEPT_REVIEW", "COMMITTEE_REVIEW", "SENATE_REVIEW",
        "REGISTRAR_REVIEW", "RETURNED", "APPROVED", "EFFECTIVE",
        "REJECTED", "WITHDRAWN",
    )


def assert_decision_record(data: dict):
    """Append-only audit row: id + created_at from the common set, and no
    updated_at / version keys ever (PRD §2.4, §3.11)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 timestamp"
    )
    assert "version" not in data, "decision records must not expose version"
    assert "updated_at" not in data, "decision records must not expose updated_at"
    for key in (
        "proposal_id", "action", "from_status", "to_status",
        "actor_role", "actor_id", "rationale", "recorded_term_id",
    ):
        assert key in data, f"decision record must carry {key}"
    assert data["action"] in (
        "SUBMIT", "APPROVE", "RETURN", "REJECT", "WITHDRAW",
        "NOTIFY", "REASSIGN_TERM", "ACTIVATE",
    )


def assert_requisite_link(data: dict):
    _assert_common_fields(data)
    assert data["requisite_type"] in ("PREREQUISITE", "COREQUISITE")
    assert is_valid_uuid(data["requisite_course_id"])
    assert is_valid_uuid(data["proposal_id"])
    assert data["status"] in ("PROPOSED", "ACTIVE", "REMOVED")


def assert_cross_listing(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["home_course_id"])
    assert is_valid_uuid(data["partner_course_id"])
    assert data["home_course_id"] != data["partner_course_id"]
    assert is_valid_uuid(data["home_department_id"])
    assert is_valid_uuid(data["partner_department_id"])
    assert data["home_department_id"] != data["partner_department_id"]
    assert data["status"] in (
        "PENDING", "HOME_APPROVED", "PARTNER_APPROVED", "ACTIVE", "REJECTED",
    )


def assert_teach_out_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["proposal_id"])
    assert is_valid_uuid(data["course_id"])
    assert isinstance(data["enrolled_cohort_count"], int)
    assert data["enrolled_cohort_count"] >= 0
    assert isinstance(data["cohort_sizes"], list)
    assert len(data["cohort_sizes"]) == data["enrolled_cohort_count"]
    assert all(isinstance(size, int) and size >= 1 for size in data["cohort_sizes"])
    assert is_valid_uuid(data["last_enrolled_term_id"])
    assert data["status"] in ("DRAFT", "COMMITTED", "IN_PROGRESS", "COMPLETE")


def assert_catalog_edition(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["edition_label"], str) and data["edition_label"]
    assert isinstance(data["academic_year"], str) and data["academic_year"]
    assert isinstance(data["year_start_date"], str)
    assert isinstance(data["year_end_date"], str)
    assert isinstance(data["included_entry_count"], int)
    assert data["included_entry_count"] >= 0
    assert data["status"] in ("DRAFT", "FROZEN", "PUBLISHED", "ARCHIVED")


def assert_catalog_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["edition_id"])
    assert is_valid_uuid(data["course_id"])
    assert is_valid_uuid(data["proposal_id"])
    assert isinstance(data["subject_code"], str) and data["subject_code"]
    assert isinstance(data["course_number"], str) and data["course_number"]
    assert isinstance(data["title"], str)
    assert isinstance(data["credit_hours"], (int, float))
    assert data["status"] in (
        "STAGED", "INCLUDED", "EXCLUDED", "PUBLISHED", "ARCHIVED",
    )
