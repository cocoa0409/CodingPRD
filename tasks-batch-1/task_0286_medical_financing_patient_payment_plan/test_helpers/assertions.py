"""Entity assertions and domain invariant checkers (PRD §2.4, §2.9)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common lifecycle fields carried by every business entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["specialty"] in ["DENTAL", "VISION", "VETERINARY", "DERMATOLOGY", "GENERAL"]
    assert isinstance(data["tax_id"], str) and len(data["tax_id"]) > 0
    assert isinstance(data["base_merchant_discount_rate"], (int, float))
    assert data["status"] in ["PENDING", "ENROLLED", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["monthly_settled_volume_cents"], int)
    assert isinstance(data["settled_net_cents"], int)


def assert_promotional_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["plan_category"] in ["DEFERRED_INTEREST", "EQUAL_PAYMENT", "REDUCED_APR"]
    assert isinstance(data["deferred_period_months"], int)
    assert isinstance(data["promo_apr"], (int, float))
    assert isinstance(data["min_payment_factor"], (int, float))
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]


def assert_provider_promotion(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["provider_id"])
    assert is_valid_uuid(data["promotional_plan_id"])
    assert is_iso8601_timestamp(data["effective_start"])
    assert is_iso8601_timestamp(data["effective_end"])
    assert data["status"] in ["ACTIVE", "WITHDRAWN"]


def assert_credit_application(data: dict):
    _assert_common(data)
    assert isinstance(data["applicant_full_name"], str) and len(data["applicant_full_name"]) > 0
    assert isinstance(data["applicant_ssn_last4"], str)
    assert isinstance(data["stated_annual_income_cents"], int)
    assert isinstance(data["requested_limit_cents"], int)
    assert isinstance(data["provisional_limit_cents"], int)
    assert data["status"] in ["SUBMITTED", "APPROVED", "DECLINED"]


def assert_patient_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["credit_application_id"])
    assert isinstance(data["account_holder_name"], str) and len(data["account_holder_name"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["current_balance_cents"], int)
    assert isinstance(data["available_credit_cents"], int)
    assert isinstance(data["delinquency_strikes"], int)
    assert data["status"] in ["ACTIVE", "DELINQUENT", "DEFAULTED", "CLOSED"]


def assert_autopay_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["patient_account_id"])
    assert isinstance(data["funding_token"], str)
    assert isinstance(data["draft_day_of_month"], int)
    assert data["status"] in ["ACTIVE", "PAUSED", "REVOKED"]


def assert_financed_purchase(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["provider_id"])
    assert is_valid_uuid(data["patient_account_id"])
    assert is_valid_uuid(data["provider_promotion_id"])
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["principal_paid_cents"], int)
    assert isinstance(data["deferred_interest_posted_cents"], int)
    assert data["settlement_status"] in ["AUTHORIZED", "SETTLED", "REFUNDED", "VOID"]
    assert data["promo_status"] in ["DEFERRED", "PAID_IN_FULL", "INTEREST_FORFEITED"]


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["financed_purchase_id"])
    assert is_valid_uuid(data["provider_id"])
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["discount_fee_cents"], int)
    assert isinstance(data["net_cents"], int)
    assert data["status"] in ["PENDING", "PAID", "CLAWED_BACK"]


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["patient_account_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["payment_type"] in ["AUTOPAY", "MANUAL", "PAYOFF"]
    assert isinstance(data["allocation"], list)
    assert data["status"] in ["POSTED", "REVERSED"]


def assert_billing_statement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["patient_account_id"])
    assert isinstance(data["minimum_payment_due_cents"], int)
    assert isinstance(data["amount_paid_in_cycle_cents"], int)
    assert isinstance(data["min_payment_satisfied"], bool)
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_refund(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["financed_purchase_id"])
    assert data["refund_kind"] in ["VOID", "REFUND"]
    assert isinstance(data["amount_cents"], int)
    assert data["status"] == "APPLIED"


# ─── Domain invariant checkers (PRD §2.9) ──────────────────────────────────
def assert_account_credit_conservation(account: dict, open_purchase_principal_sum: int):
    """Credit conservation (PRD §2.9): available_credit_cents always equals
    credit_limit_cents minus the principal of still-open purchases."""
    assert account["available_credit_cents"] == (
        account["credit_limit_cents"] - open_purchase_principal_sum
    ), (
        f"credit conservation violated: available={account['available_credit_cents']}, "
        f"limit={account['credit_limit_cents']}, open_principal={open_purchase_principal_sum}"
    )


def assert_balance_non_negative(account: dict):
    """The current balance is floored at zero and never goes negative (PRD §3.4)."""
    assert account["current_balance_cents"] >= 0, "current_balance_cents must never be negative"
