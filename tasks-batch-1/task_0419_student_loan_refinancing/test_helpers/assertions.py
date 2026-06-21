"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

FICO_BANDS = ["SUBPRIME", "NEAR_PRIME", "PRIME", "SUPER_PRIME"]
MEMBER_TIERS = ["NONE", "SILVER", "GOLD", "PLATINUM"]


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version (entities with common_fields)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def _assert_append_only_fields(data: dict):
    """id + created_at only; no updated_at, no version (append-only records)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not expose updated_at"
    assert "version" not in data, "append-only record must not expose version"


def assert_borrower(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["annual_income_cents"], int) and data["annual_income_cents"] >= 0
    assert data["fico_band"] in FICO_BANDS
    assert data["member_tier"] in MEMBER_TIERS


def assert_abs_pool(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pool_code"], str) and len(data["pool_code"]) > 0
    assert isinstance(data["max_principal_cents"], int) and data["max_principal_cents"] > 0
    assert data["min_fico_band"] in FICO_BANDS
    assert data["allowed_rate_type"] in ["FIXED", "VARIABLE", "ANY"]
    assert isinstance(data["committed_principal_cents"], int) and data["committed_principal_cents"] >= 0
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_rate_grid_entry(data: dict):
    _assert_append_only_fields(data)
    assert data["rate_type"] in ["FIXED", "VARIABLE"]
    assert data["term_months"] in [60, 84, 120, 180, 240]
    assert data["min_fico_band"] in FICO_BANDS
    assert isinstance(data["base_apr_bps"], int) and data["base_apr_bps"] > 0
    assert isinstance(data["index_apr_bps"], int) and data["index_apr_bps"] >= 0


def assert_application(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["borrower_id"])
    assert isinstance(data["requested_principal_cents"], int) and data["requested_principal_cents"] > 0
    assert data["requested_term_months"] in [60, 84, 120, 180, 240]
    assert data["requested_rate_type"] in ["FIXED", "VARIABLE"]
    assert data["status"] in [
        "DRAFT", "PREQUALIFIED", "UNDER_REVIEW", "APPROVED", "DECLINED", "EXPIRED", "WITHDRAWN"
    ]


def assert_offer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert data["term_months"] in [60, 84, 120, 180, 240]
    assert data["rate_type"] in ["FIXED", "VARIABLE"]
    assert isinstance(data["estimated_apr_bps"], int) and data["estimated_apr_bps"] > 0
    assert data["status"] in ["PRESENTED", "LOCKED", "EXPIRED", "SUPERSEDED"]
    assert is_iso8601_timestamp(data["expires_at"]), "expires_at must be ISO 8601"


def assert_cosigner(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["cosigner_email"], str) and len(data["cosigner_email"]) > 0
    assert isinstance(data["cosigner_annual_income_cents"], int) and data["cosigner_annual_income_cents"] >= 0
    assert data["consent_status"] in ["INVITED", "CONSENTED", "DECLINED", "RELEASED"]
    assert isinstance(data["on_time_streak"], int) and data["on_time_streak"] >= 0


def assert_loan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["offer_id"])
    assert isinstance(data["original_principal_cents"], int) and data["original_principal_cents"] > 0
    assert isinstance(data["principal_balance_cents"], int) and data["principal_balance_cents"] >= 0
    assert isinstance(data["accrued_interest_cents"], int) and data["accrued_interest_cents"] >= 0
    assert isinstance(data["locked_apr_bps"], int) and data["locked_apr_bps"] > 0
    assert data["repayment_status"] in [
        "CURRENT", "FORBEARANCE", "DELINQUENT", "PAID_OFF", "CHARGED_OFF"
    ]
    assert data["cosigner_release_status"] in [
        "PENDING", "ELIGIBLE", "RELEASED", "NOT_APPLICABLE"
    ]


def assert_disbursement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["prior_servicer_name"], str) and len(data["prior_servicer_name"]) > 0
    assert isinstance(data["payoff_amount_cents"], int) and data["payoff_amount_cents"] > 0
    assert data["status"] in ["SCHEDULED", "SENT", "CONFIRMED", "RETURNED"]


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["on_time"], bool)
    assert isinstance(data["interest_portion_cents"], int) and data["interest_portion_cents"] >= 0
    assert isinstance(data["principal_portion_cents"], int) and data["principal_portion_cents"] >= 0


def assert_forbearance_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["loan_id"])
    assert data["reason_code"] in ["JOB_LOSS", "MEDICAL", "NATURAL_DISASTER", "OTHER"]
    assert isinstance(data["months_requested"], int)
    assert isinstance(data["interest_capitalized_cents"], int) and data["interest_capitalized_cents"] >= 0
    assert data["status"] in ["ACTIVE", "ENDED"]


def assert_audit_event(data: dict):
    _assert_append_only_fields(data)
    assert data["subject_type"] in ["APPLICATION", "LOAN", "COSIGNER", "DISBURSEMENT"]
    assert is_valid_uuid(data["subject_id"])
    assert isinstance(data["action"], str) and len(data["action"]) > 0


def assert_payment_waterfall_conserves(payment: dict):
    """interest_portion + principal_portion <= amount; no cent created (PRD 3.9)."""
    total_allocated = payment["interest_portion_cents"] + payment["principal_portion_cents"]
    assert total_allocated <= payment["amount_cents"], (
        f"allocated {total_allocated} cannot exceed paid {payment['amount_cents']}"
    )
