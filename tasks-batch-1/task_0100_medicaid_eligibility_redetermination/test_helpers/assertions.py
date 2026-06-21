"""Entity assertions and domain invariant checkers.

Per-entity assert_{entity}(data) validate the shape and field domains the PRD
declares for each resource. Domain invariant checkers verify the conserved
member-month ledger that must hold after every coverage change.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (resources with the full common set)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_state_rule(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["is_expansion_state"], bool)
    assert isinstance(data["magi_adult_threshold_pct"], int)
    assert isinstance(data["magi_child_threshold_pct"], int)
    assert isinstance(data["abd_asset_limit_cents"], int)
    assert isinstance(data["standard_asset_limit_cents"], int)
    assert isinstance(data["continuous_coverage_active"], bool)


def assert_fpl_schedule(data: dict):
    """FplSchedule is immutable: ONLY id + created_at (no updated_at / version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["year"], int)
    assert isinstance(data["base_annual_cents"], int)
    assert isinstance(data["per_member_increment_cents"], int)


def assert_household(data: dict):
    _assert_common(data)
    assert isinstance(data["state_code"], str)
    assert isinstance(data["fpl_year"], int)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 0
    assert isinstance(data["primary_applicant_name"], str)
    assert isinstance(data["covered_member_months"], int) and data["covered_member_months"] >= 0
    assert isinstance(data["active_enrollment_count"], int) and data["active_enrollment_count"] >= 0


def assert_member(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("household_id", "")), "household_id must be a valid UUID"
    assert isinstance(data["full_name"], str)
    assert isinstance(data["age"], int) and data["age"] >= 0
    assert data["relationship"] in ["SELF", "SPOUSE", "CHILD", "DEPENDENT", "OTHER"]
    assert isinstance(data["is_disabled"], bool)
    assert data["member_status"] in ["COUNTED", "EXCLUDED"]


def assert_income_source(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a valid UUID"
    assert data["income_type"] in [
        "WAGES", "SELF_EMPLOYMENT", "SOCIAL_SECURITY", "CHILD_SUPPORT", "TANF", "GIFT"
    ]
    assert isinstance(data["monthly_amount_cents"], int) and data["monthly_amount_cents"] >= 0
    assert isinstance(data["is_magi_countable"], bool)
    assert isinstance(data["projected_annual_cents"], int)


def assert_asset(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("household_id", "")), "household_id must be a valid UUID"
    assert data["asset_type"] in ["CASH", "BANK_ACCOUNT", "VEHICLE", "HOME", "RETIREMENT", "BURIAL_FUND"]
    assert isinstance(data["value_cents"], int) and data["value_cents"] >= 0
    assert isinstance(data["is_exempt"], bool)
    assert isinstance(data["countable_value_cents"], int) and data["countable_value_cents"] >= 0


def assert_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("household_id", "")), "household_id must be a valid UUID"
    assert data["pathway"] in ["MAGI", "NON_MAGI"]
    assert data["magi_variant"] in ["POINT_IN_TIME", "PROJECTED_ANNUAL"]
    assert data["review_status"] in ["DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED"]
    assert data["verification_status"] in ["UNVERIFIED", "DOCS_REQUESTED", "VERIFIED"]


def assert_determination(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a valid UUID"
    assert data["pathway"] in ["MAGI", "NON_MAGI"]
    assert data["decision"] in ["ELIGIBLE", "INELIGIBLE"]
    assert data["decision_reason"] in [
        "INCOME_UNDER_THRESHOLD", "INCOME_OVER_THRESHOLD",
        "ASSETS_UNDER_LIMIT", "ASSETS_OVER_LIMIT",
    ]


def assert_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("household_id", "")), "household_id must be a valid UUID"
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a valid UUID"
    assert data["coverage_status"] in ["PENDING", "ACTIVE", "IN_REDETERMINATION", "TERMINATED"]
    assert isinstance(data["member_months"], int) and data["member_months"] >= 0


def assert_redetermination(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", "")), "enrollment_id must be a valid UUID"
    assert data["redet_status"] in [
        "INITIATED", "INFO_REQUESTED", "RENEWED", "TERMINATED", "PENDING_APPEAL"
    ]
    assert isinstance(data["info_request_count"], int) and data["info_request_count"] >= 0


def assert_appeal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", "")), "enrollment_id must be a valid UUID"
    assert is_valid_uuid(data.get("redetermination_id", "")), "redetermination_id must be a valid UUID"
    assert data["appeal_status"] in [
        "FILED", "HEARING_SCHEDULED", "HEARD", "UPHELD", "OVERTURNED", "WITHDRAWN"
    ]


def assert_ledger_invariants(household: dict, expected_member_months: int,
                             expected_active_count: int):
    """The conserved member-month ledger invariants (PRD §2.6).

    covered_member_months == sum of member_months over ACTIVE/IN_REDETERMINATION
    enrollments; active_enrollment_count == count of those enrollments. Both are
    integers that must hold exactly after every cascade settles.
    """
    assert household["covered_member_months"] == expected_member_months, (
        f"covered_member_months expected {expected_member_months}, "
        f"got {household['covered_member_months']}"
    )
    assert household["active_enrollment_count"] == expected_active_count, (
        f"active_enrollment_count expected {expected_active_count}, "
        f"got {household['active_enrollment_count']}"
    )
