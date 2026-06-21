"""Entity assertions and domain invariant checkers for the LIHTC Compliance API.

Each assert_{entity} validates the response shape against the PRD contract using the
framework's generic format validators. Domain invariant checkers verify cross-field rules
stated in the PRD (e.g. is_low_income_counted ⟺ li_status in {QUALIFIED, OVER_INCOME}).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """All entities carry id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_project(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["area_median_income_cents"], int)
    assert data["minimum_set_aside"] in ("TWENTY_FIFTY", "FORTY_SIXTY", "AVERAGE_INCOME")
    assert data["status"] in (
        "DRAFT", "SET_ASIDE_MET", "CREDIT_PERIOD", "COMPLIANCE_PERIOD", "CLOSED"
    )
    assert data["posture"] in ("COMPLIANT", "AT_RISK", "NONCOMPLIANT")
    assert isinstance(data["open_finding_count"], int)
    assert data["open_finding_count"] >= 0


def assert_building(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["eligible_basis_cents"], int)
    assert data["credit_type"] in ("NINE_PERCENT", "FOUR_PERCENT")
    assert isinstance(data["total_residential_units"], int)
    assert isinstance(data["total_residential_sqft"], int)
    assert isinstance(data["applicable_fraction"], (int, float))
    assert isinstance(data["qualified_basis_cents"], int)
    assert isinstance(data["annual_credit_cents"], int)
    assert data["credit_status"] in (
        "PRE_ALLOCATION", "PROVISIONAL_8609", "FINAL_8609", "RECAPTURED"
    )


def assert_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["building_id"], str)
    assert isinstance(data["bedroom_count"], int)
    assert 0 <= data["bedroom_count"] <= 3
    assert data["ami_designation"] in ("AMI_40", "AMI_50", "AMI_60", "AMI_80", "MARKET")
    assert data["li_status"] in (
        "VACANT_NEVER_OCCUPIED", "QUALIFIED", "OVER_INCOME", "DISQUALIFIED", "MARKET_RENTED"
    )
    assert isinstance(data["is_low_income_counted"], bool)
    assert_unit_li_invariant(data)


def assert_unit_li_invariant(data: dict):
    """is_low_income_counted is true exactly when li_status is QUALIFIED or OVER_INCOME
    (PRD §3.5)."""
    expected = data["li_status"] in ("QUALIFIED", "OVER_INCOME")
    assert data["is_low_income_counted"] is expected, (
        f"is_low_income_counted should be {expected} for li_status "
        f"{data['li_status']}, got {data['is_low_income_counted']}"
    )


def assert_household(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["all_full_time_students"], bool)
    assert data["student_exception"] in (
        "NONE", "TANF", "JOB_TRAINING", "SINGLE_PARENT",
        "MARRIED_JOINT_FILER", "FORMER_FOSTER",
    )
    assert isinstance(data["student_eligible"], bool)


def assert_certification(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["household_id"], str)
    assert isinstance(data["unit_id"], str)
    assert data["cert_type"] in ("INITIAL", "RECERT")
    assert isinstance(data["annual_income_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")
    assert isinstance(data["is_over_income"], bool)


def assert_lease(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["household_id"], str)
    assert isinstance(data["unit_id"], str)
    assert isinstance(data["monthly_rent_cents"], int)
    assert data["status"] == "ACTIVE"


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["building_id"], str)
    assert isinstance(data["deduction_points"], list)
    assert isinstance(data["has_exigent_health_safety"], bool)
    assert data["result"] in ("PASS", "FAIL")
    assert data["status"] in ("SCHEDULED", "CONDUCTED", "CLOSED")


def assert_finding(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["building_id"], str)
    assert data["category"] in (
        "OVER_INCOME_UNCURED", "STUDENT_VIOLATION", "RENT_OVERCHARGE",
        "UPCS_FAIL", "SET_ASIDE_FAILURE", "AVAILABLE_UNIT_VIOLATION",
    )
    assert data["status"] in ("OPEN", "CORRECTED", "REPORTED_8823")


def assert_form8609(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["building_id"], str)
    assert data["issuance_type"] in ("PROVISIONAL", "FINAL")
    assert isinstance(data["allocated_fraction"], (int, float))
    assert isinstance(data["allocated_annual_credit_cents"], int)
    assert data["status"] in ("ISSUED", "REVOKED")
