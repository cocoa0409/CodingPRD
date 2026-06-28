"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import BUREAUS


def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["kyc_status"] in ["PENDING", "VERIFIED", "REJECTED"]
    assert data["disclosure_status"] in ["UNACKNOWLEDGED", "ACKNOWLEDGED"]
    assert data["posture"] in ["BLOCKED", "ELIGIBLE", "FROZEN"]
    assert data["status"] in ["OPEN", "FROZEN", "CLOSED"]
    assert isinstance(data["wallet_cents"], int) and data["wallet_cents"] >= 0
    assert isinstance(data["version"], int)


def assert_disclosure(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["product_kind"] in ["LOAN", "SECURED_CARD"]
    assert isinstance(data["apr_bps"], int) and data["apr_bps"] >= 0
    assert isinstance(data["admin_fee_cents"], int) and data["admin_fee_cents"] >= 0
    assert data["status"] in ["ISSUED", "ACKNOWLEDGED", "SUPERSEDED"]


def assert_loan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["lifecycle_status"] in [
        "PENDING", "ACTIVE", "PAID_OFF", "GRADUATED", "DEFAULTED", "CANCELLED"
    ]
    assert data["delinquency_status"] in [
        "CURRENT", "DPD_30", "DPD_60", "DPD_90", "CHARGED_OFF"
    ]
    assert isinstance(data["principal_cents"], int)
    assert data["term_months"] in [12, 24]
    assert isinstance(data["outstanding_principal_cents"], int)
    assert data["outstanding_principal_cents"] >= 0, "outstanding principal never negative"
    assert isinstance(data["version"], int)


def assert_installment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["period_index"], int) and data["period_index"] >= 1
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["principal_component_cents"], int)
    assert isinstance(data["interest_component_cents"], int)
    assert data["status"] in ["SCHEDULED", "PAID", "LATE"]


def assert_payment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["source"] in ["MANUAL", "AUTOPAY"]
    assert data["status"] == "POSTED"
    assert isinstance(data["applied_principal_cents"], int)
    assert isinstance(data["applied_interest_cents"], int)
    assert isinstance(data["applied_fee_cents"], int)


def assert_secured_card(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["status"] in ["PENDING", "FUNDED", "ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["balance_cents"], int) and data["balance_cents"] >= 0
    assert isinstance(data["graduation_eligible"], bool)


def assert_card_deposit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ["POSTED", "RELEASED"]


def assert_autopay(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["day_of_month"], int)
    assert isinstance(data["funding_wallet"], bool)
    assert data["status"] in ["ACTIVE", "PAUSED", "CANCELLED"]


def assert_payoff_quote(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["payoff_amount_cents"], int)
    assert isinstance(data["scheduled_remaining_cents"], int)
    assert isinstance(data["interest_savings_cents"], int)
    assert data["status"] in ["ACTIVE", "CONSUMED", "EXPIRED"]


def assert_bureau_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["tradeline_kind"] in ["LOAN", "SECURED_CARD"]
    assert data["payment_rating"] in ["ON_TIME", "LATE_30", "LATE_60", "LATE_90", "CHARGE_OFF"]
    # PRD §2.4 / §3.12: append-only audit record carries no version / updated_at.
    assert "version" not in data, "BureauReport is append-only: must have no version field"
    assert "updated_at" not in data, "BureauReport is append-only: must have no updated_at field"


def assert_bureaus_are_three(data: dict):
    """PRD §3.12: the bureaus array is always the three national bureaus."""
    assert data["bureaus"] == BUREAUS, (
        f"bureaus must be {BUREAUS}, got {data.get('bureaus')}"
    )


def assert_score_snapshot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["simulated_score"], int)
    assert 300 <= data["simulated_score"] <= 850, "score clamped to [300, 850]"
    assert isinstance(data["score_delta"], int)
    # PRD §2.4: append-only audit record carries no version / updated_at.
    assert "version" not in data, "ScoreSnapshot is append-only: must have no version field"
    assert "updated_at" not in data, "ScoreSnapshot is append-only: must have no updated_at field"
