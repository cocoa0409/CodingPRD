"""Entity assertions and domain invariant checkers (PRD Sections 2.5, 3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    """Fields every versioned entity carries (PRD Section 2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def _assert_append_only(data: dict, entity: str):
    """Payroll entries and evaluation records carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, f"{entity} must not carry updated_at"
    assert "version" not in data, f"{entity} must not carry version"


def assert_department(data: dict):
    _assert_common(data, "Department")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str)
    assert isinstance(data["contact_hour_value"], (int, float))
    assert data["contact_hour_value"] > 0
    assert isinstance(data["active"], bool)


def assert_term(data: dict):
    _assert_common(data, "TermConfig")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    for f in ("start_date", "end_date", "early_census_date", "late_census_date"):
        assert isinstance(data[f], str) and len(data[f]) == 10, f"{f} must be an ISO date"
    assert isinstance(data["load_cap_units"], (int, float)) and data["load_cap_units"] > 0
    assert data["rollover_status"] in ("SCHEDULED", "OPEN", "ROLLED_OVER")


def assert_rate_schedule(data: dict):
    _assert_common(data, "RateSchedule")
    assert is_valid_uuid(data.get("department_id", ""))
    assert data["education_tier"] in ("BACHELORS", "MASTERS", "DOCTORATE")
    assert data["rate_basis"] in ("PER_CONTACT_HOUR", "PER_COURSE")
    assert isinstance(data["base_rate_cents"], int) and data["base_rate_cents"] >= 1
    assert isinstance(data["longevity_step_cents"], int) and data["longevity_step_cents"] >= 0
    assert isinstance(data["longevity_step_cap"], int) and data["longevity_step_cap"] >= 0
    assert data["schedule_status"] in ("DRAFT", "PUBLISHED", "RETIRED")


def assert_posting(data: dict):
    _assert_common(data, "AdjunctPoolPosting")
    assert is_valid_uuid(data.get("department_id", ""))
    assert isinstance(data["term_code"], str)
    assert isinstance(data["title"], str)
    assert data["min_education_tier"] in ("BACHELORS", "MASTERS", "DOCTORATE")
    assert data["posting_status"] in ("DRAFT", "OPEN", "SUSPENDED", "CLOSED", "ARCHIVED")


def assert_application(data: dict):
    _assert_common(data, "AdjunctApplication")
    assert is_valid_uuid(data.get("posting_id", ""))
    assert isinstance(data["applicant_name"], str)
    assert isinstance(data["applicant_email"], str)
    assert data["claimed_education_tier"] in ("BACHELORS", "MASTERS", "DOCTORATE")
    assert data["application_status"] in (
        "SUBMITTED", "UNDER_REVIEW", "RETURNED_FOR_REVISION",
        "APPROVED", "REJECTED", "WITHDRAWN", "EXPIRED",
    )
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_credential(data: dict):
    _assert_common(data, "CredentialVerification")
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["kind"] in ("TRANSCRIPT", "DEGREE", "LICENSE", "BACKGROUND_CHECK", "TRAINING")
    assert isinstance(data["evidence_ref"], str)
    assert data["verification_status"] in ("PENDING", "VERIFIED", "REJECTED")


def assert_faculty(data: dict):
    _assert_common(data, "AdjunctFaculty")
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("department_id", ""))
    assert isinstance(data["legal_name"], str)
    assert data["education_tier"] in ("BACHELORS", "MASTERS", "DOCTORATE")
    assert data["compliance_status"] in ("ONBOARDING", "COMPLIANT", "LAPSED")
    assert data["retention_status"] in ("PROVISIONAL", "RETENTION_LISTED", "NON_REAPPOINTED")
    assert isinstance(data["completed_terms"], int) and data["completed_terms"] >= 0
    assert isinstance(data["current_term_load_units"], (int, float))
    assert isinstance(data["benefits_eligible"], bool)


def assert_section(data: dict):
    _assert_common(data, "CourseSection")
    assert is_valid_uuid(data.get("department_id", ""))
    assert isinstance(data["term_code"], str)
    assert isinstance(data["course_code"], str)
    assert isinstance(data["section_code"], str)
    assert isinstance(data["weekly_contact_hours"], (int, float))
    assert data["weekly_contact_hours"] > 0
    assert isinstance(data["credit_hours"], int) and data["credit_hours"] >= 0
    assert isinstance(data["enrollment"], int) and data["enrollment"] >= 0
    assert isinstance(data["min_enrollment"], int) and data["min_enrollment"] >= 0
    assert data["section_status"] in ("SCHEDULED", "RUNNING", "CANCELLED", "COMPLETED")


def assert_contract(data: dict):
    _assert_common(data, "Contract")
    assert is_valid_uuid(data.get("faculty_id", ""))
    assert is_valid_uuid(data.get("section_id", ""))
    assert is_valid_uuid(data.get("rate_schedule_id", ""))
    assert isinstance(data["load_units"], (int, float))
    assert isinstance(data["gross_pay_cents"], int)
    assert isinstance(data["payable_cents"], int)
    assert data["contract_status"] in (
        "ISSUED", "ACTIVE", "CANCELLED_PRE_CENSUS",
        "CANCELLED_LATE", "COMPLETED", "VOIDED",
    )


def assert_payroll_period(data: dict):
    _assert_common(data, "PayrollPeriod")
    assert isinstance(data["period_code"], str) and len(data["period_code"]) > 0
    assert isinstance(data["start_date"], str) and len(data["start_date"]) == 10
    assert isinstance(data["end_date"], str) and len(data["end_date"]) == 10
    assert data["period_status"] in ("OPEN", "LOCKED", "CLOSED")


def assert_payroll_entry(data: dict):
    _assert_append_only(data, "PayrollEntry")
    assert is_valid_uuid(data.get("contract_id", ""))
    assert is_valid_uuid(data.get("payroll_period_id", ""))
    assert data["entry_kind"] in ("ACCRUAL", "CANCELLATION_PAYOUT", "CLAWBACK")
    assert isinstance(data["amount_cents"], int), "amount_cents must be integer cents"
    assert data["split_variant"] in ("EQUAL_SPLIT", "DAYS_WEIGHTED")


def assert_evaluation(data: dict):
    _assert_append_only(data, "EvaluationRecord")
    assert is_valid_uuid(data.get("faculty_id", ""))
    assert isinstance(data["term_code"], str)
    for f in ("teaching_score", "service_score", "compliance_score", "composite_score"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
        assert 0 <= data[f] <= 5, f"{f} out of 0..5 range"


def assert_retention_entry(data: dict):
    _assert_common(data, "RetentionEntry")
    assert is_valid_uuid(data.get("faculty_id", ""))
    assert is_valid_uuid(data.get("department_id", ""))
    assert isinstance(data["list_term_code"], str)
    assert isinstance(data["rank_position"], int) and data["rank_position"] >= 1
    assert data["entry_status"] in ("LISTED", "REAPPOINTED", "NON_REAPPOINTED")


def assert_load_read(data: dict):
    """Computed load read shape (PRD Section 3.4)."""
    assert isinstance(data["load_units"], (int, float))
    assert isinstance(data["variant"], str)
    assert isinstance(data["term_code"], str)
    assert isinstance(data["load_cap_units"], (int, float))
    assert isinstance(data["benefits_eligible"], bool)
