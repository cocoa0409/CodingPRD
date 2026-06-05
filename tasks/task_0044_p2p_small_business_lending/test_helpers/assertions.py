"""Entity assertions and domain invariant checkers.

Field names match the PRD exactly. These verify structural well-formedness; the
test files carry the value-bearing assertions sourced from the design indices.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_borrower(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int), "version must be int"
    assert isinstance(data["business_name"], str) and len(data["business_name"]) > 0
    assert isinstance(data["ein"], str) and len(data["ein"]) > 0
    assert isinstance(data["state_code"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_loan_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int)
    assert is_valid_uuid(data.get("borrower_id", "")), "borrower_id must be a UUID"
    assert isinstance(data["requested_principal_cents"], int)
    assert data["term_months"] in (12, 24, 36, 60)
    assert isinstance(data["plaid_avg_monthly_revenue_cents"], int)
    assert isinstance(data["plaid_monthly_debt_payment_cents"], int)
    assert isinstance(data["plaid_nsf_count_90d"], int)
    assert isinstance(data["plaid_account_age_months"], int)
    assert data["status"] in ("SUBMITTED", "SCORED", "APPROVED", "REJECTED")


def assert_loan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int)
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a UUID"
    assert is_valid_uuid(data.get("borrower_id", "")), "borrower_id must be a UUID"
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["apr"], (int, float))
    assert data["term_months"] in (12, 24, 36, 60)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int)
    assert isinstance(data["late_fee_outstanding_cents"], int)
    assert isinstance(data["current_period_index"], int)
    assert isinstance(data["missed_payment_count"], int)
    assert isinstance(data["last_assessed_period_index"], int)
    assert data["status"] in (
        "FUNDING", "ACTIVE", "REPAYMENT", "PAID_OFF", "DEFAULTED", "CHARGED_OFF",
    )


def assert_investor(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert isinstance(data["capital_base_cents"], int)
    assert isinstance(data["committed_capital_cents"], int)
    assert isinstance(data["max_single_loan_pct"], (int, float))
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_investment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int)
    assert is_valid_uuid(data.get("investor_id", "")), "investor_id must be a UUID"
    assert is_valid_uuid(data.get("loan_id", "")), "loan_id must be a UUID"
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["outstanding_principal_cents"], int)
    assert isinstance(data["charged_off_basis_cents"], int)
    assert data["status"] in ("COMMITTED", "WRITTEN_OFF")


def assert_repayment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int)
    assert is_valid_uuid(data.get("loan_id", "")), "loan_id must be a UUID"
    assert isinstance(data["amount_cents"], int)
    assert data["kind"] in ("SCHEDULED", "RECOVERY")
    assert isinstance(data["late_fee_paid_cents"], int)
    assert isinstance(data["interest_paid_cents"], int)
    assert isinstance(data["principal_paid_cents"], int)
    assert isinstance(data["platform_fee_cents"], int)


def assert_compliance_disclosure(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int)
    assert is_valid_uuid(data.get("loan_id", "")), "loan_id must be a UUID"
    assert data["document_type"] in (
        "SERIES_NOTE_PROSPECTUS", "RISK_FACTORS", "ANNUAL_REPORT",
    )
    assert data["status"] in ("FILED", "SUPERSEDED")


def assert_repayment_allocation(data: dict):
    """RepaymentAllocation is append-only: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "RepaymentAllocation must NOT carry a version field"
    assert "updated_at" not in data, "RepaymentAllocation must NOT carry an updated_at field"


def assert_no_version_field(data: dict):
    """Helper for immutability checks on append-only allocation rows."""
    assert "version" not in data, "row must not carry a version field"
    assert "updated_at" not in data, "row must not carry an updated_at field"
