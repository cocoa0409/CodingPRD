"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_landlord(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["phone_number"], str)


def assert_renter(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["phone_number"], str)


def assert_property(data: dict):
    assert_common_fields(data)
    assert isinstance(data["landlord_id"], str)
    assert data["program_status"] in ["PENDING_REVIEW", "ACTIVE", "TERMINATED"]
    assert data["property_type"] in ["SINGLE_FAMILY", "MULTI_FAMILY", "CONDO"]
    assert isinstance(data["monthly_rent_cents"], int) and data["monthly_rent_cents"] > 0
    assert isinstance(data["total_paid_claims_cents"], int) and data["total_paid_claims_cents"] >= 0


def assert_state_compliance_rule(data: dict):
    # common_fields: false — only id + created_at, no updated_at/version.
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["enrollment_allowed"], bool)
    assert 0 < data["max_monthly_fee_pct_of_rent"] <= 1


def assert_renter_enrollment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING_UNDERWRITING", "MANUAL_REVIEW", "APPROVED", "DECLINED"]
    assert data["payment_plan"] in ["MONTHLY", "ANNUAL_UPFRONT"]
    assert isinstance(data["requested_coverage_limit_cents"], int)
    assert 300 <= data["credit_proxy_score"] <= 850


def assert_policy(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["AWAITING_FIRST_PAYMENT", "ACTIVE", "LAPSED", "CANCELLED", "EXPIRED"]
    assert isinstance(data["coverage_limit_cents"], int)
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["gross_available_coverage_cents"], int)
    assert isinstance(data["net_available_coverage_cents"], int)


def assert_premium_invoice(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["ISSUED", "PAID", "OVERDUE"]
    assert data["amount_cents"] == data["insurance_premium_cents"] + data["platform_fee_cents"] + data["state_tax_cents"]


def assert_claim(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["UNDER_REVIEW", "NEEDS_INFO", "APPROVED", "DENIED", "CLOSED"]
    assert data["claim_type"] in ["UNPAID_RENT", "PROPERTY_DAMAGE", "BOTH"]
    assert isinstance(data["line_items"], list)
    assert data["total_claimed_amount_cents"] == sum(li["amount_cents"] for li in data["line_items"])


def assert_payout(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["PENDING", "DISBURSED", "REVERSED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_subrogation_case(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["OPEN", "DEMAND_SENT", "PAID_IN_FULL", "WRITTEN_OFF"]
    assert isinstance(data["original_demand_amount_cents"], int) and data["original_demand_amount_cents"] > 0
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_recovery_payment(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SUCCEEDED", "REVERSED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_policy_coverage_invariant(policy: dict, disbursed_payout_total_cents: int):
    """PRD §2.8: coverage_limit == net_available + sum(non-reversed DISBURSED payouts)."""
    assert policy["coverage_limit_cents"] == policy["net_available_coverage_cents"] + disbursed_payout_total_cents


def assert_subrogation_balance_invariant(case: dict, succeeded_payment_total_cents: int):
    """PRD §2.8: original_demand == outstanding_balance + sum(non-reversed SUCCEEDED payments)."""
    assert case["original_demand_amount_cents"] == case["outstanding_balance_cents"] + succeeded_payment_total_cents
