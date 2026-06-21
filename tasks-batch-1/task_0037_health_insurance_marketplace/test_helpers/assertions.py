"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_household(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["coverage_year"], int)
    assert isinstance(data["rating_area"], str)
    assert isinstance(data["household_magi_cents"], int)
    assert data["household_magi_cents"] >= 0
    assert isinstance(data["countable_size"], int) and data["countable_size"] >= 0
    assert isinstance(data["fpl_percent"], (int, float))


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["relationship"] in ["PRIMARY", "SPOUSE", "DEPENDENT"]
    assert data["tax_filing_status"] in [
        "FILER", "JOINT_FILER", "DEPENDENT_FILER", "DEPENDENT_NONFILER"]
    assert isinstance(data["annual_income_cents"], int) and data["annual_income_cents"] >= 0
    assert isinstance(data["applies_for_coverage"], bool)
    assert isinstance(data["is_countable_income"], bool)


def assert_health_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # common_fields: false — no version / updated_at on a HealthPlan.
    assert "version" not in data, "HealthPlan must not carry a version field"
    assert "updated_at" not in data, "HealthPlan must not carry an updated_at field"
    assert data["metal_tier"] in ["BRONZE", "SILVER", "GOLD", "PLATINUM"]
    assert isinstance(data["gross_premium_cents"], int) and data["gross_premium_cents"] > 0
    assert isinstance(data["csr_eligible"], bool)


def assert_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in ["DRAFT", "SUBMITTED", "DETERMINED", "ENROLLED", "CANCELLED"]
    assert data["enrollment_window"] in ["OEP", "SEP"]


def assert_determination(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["fpl_percent_snapshot"], (int, float))
    assert isinstance(data["applicable_pct"], (int, float))
    assert isinstance(data["max_aptc_monthly_cents"], int) and data["max_aptc_monthly_cents"] >= 0
    assert data["csr_tier"] in ["CSR94", "CSR87", "CSR73", "NONE"]
    assert isinstance(data["is_subsidy_eligible"], bool)


def assert_enrollment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["applied_aptc_monthly_cents"], int)
    assert isinstance(data["net_premium_monthly_cents"], int)
    assert isinstance(data["first_month_premium_cents"], int)
    assert isinstance(data["effective_date"], str)
    assert data["lifecycle_status"] in ["PENDING_EFFECTUATION", "ACTIVE", "TERMINATED"]
    assert data["payment_status"] in ["AWAITING_BINDER", "PAID", "DELINQUENT"]


def assert_sep_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["qualifying_event_type"] in [
        "BIRTH", "ADOPTION", "MARRIAGE", "LOSS_OF_COVERAGE", "PERMANENT_MOVE"]
    assert data["status"] in ["PENDING", "APPROVED", "DENIED"]
    assert isinstance(data["window_close_date"], str)


def assert_reconciliation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["advanced_aptc_total_cents"], int)
    assert isinstance(data["allowed_aptc_total_cents"], int)
    assert isinstance(data["settlement_cents"], int)
