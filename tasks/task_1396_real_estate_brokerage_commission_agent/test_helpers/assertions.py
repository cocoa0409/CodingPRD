"""Entity assertions and domain invariant checkers (PRD §2.5, §2.11)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, has_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if has_version:
        assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    else:
        assert "version" not in data, "append-only ledger row must NOT carry version"
        assert "updated_at" not in data, "append-only ledger row must NOT carry updated_at"


def assert_agent(data: dict):
    _assert_common(data, has_version=True)
    assert data["status"] in ["ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert isinstance(data["joined_at"], str) and data["joined_at"]
    assert isinstance(data["debit_balance_cents"], int) and data["debit_balance_cents"] >= 0
    assert isinstance(data["settled_deal_count"], int) and data["settled_deal_count"] >= 0


def assert_plan(data: dict):
    _assert_common(data, has_version=True)
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["royalty_cap_cents"], int)
    assert isinstance(data["eo_fee_cents"], int)
    assert isinstance(data["transaction_fee_cents"], int)
    assert isinstance(data["tiers"], list) and len(data["tiers"]) > 0


def assert_enrollment(data: dict):
    _assert_common(data, has_version=True)
    assert data["status"] in ["SCHEDULED", "ACTIVE", "SUPERSEDED", "ENDED", "CANCELLED"]
    assert is_valid_uuid(data["agent_id"])
    assert is_valid_uuid(data["plan_id"])
    assert isinstance(data["plan_version"], int)
    assert isinstance(data["effective_from"], str)


def assert_anniversary_period(data: dict):
    _assert_common(data, has_version=True)
    assert data["status"] in ["OPEN", "CLOSED"]
    assert isinstance(data["window_index"], int) and data["window_index"] >= 0
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert isinstance(data["company_dollar_accrued_cents"], int)
    assert isinstance(data["royalty_accrued_cents"], int)


def assert_deal(data: dict):
    _assert_common(data, has_version=True)
    assert data["status"] in ["DRAFT", "PENDING_CLOSING", "CLOSED", "SETTLED", "DISBURSED", "FELL_THROUGH", "VOIDED"]
    assert isinstance(data["gross_commission_cents"], int)
    assert isinstance(data["closing_date"], str)
    assert isinstance(data["trust_received_cents"], int)


def assert_settlement(data: dict):
    _assert_common(data, has_version=True)
    assert data["status"] in ["POSTED", "REVERSED"]
    for f in (
        "gross_commission_cents", "cobroke_payout_cents", "net_office_commission_cents",
        "referral_fee_cents", "adjusted_commission_cents", "royalty_cents",
        "after_royalty_cents", "company_dollar_cents", "agent_gross_cents",
        "mentor_split_cents", "team_override_cents", "eo_fee_cents",
        "transaction_fee_cents", "fee_shortfall_cents", "debit_recovery_cents",
        "agent_net_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be int"
    assert isinstance(data["royalty_capped"], bool)
    assert isinstance(data["cap_clipped"], bool)
    assert isinstance(data["mentor_applied"], bool)
    assert isinstance(data["tier_index_applied"], int)


def assert_disbursement_leg(data: dict):
    _assert_common(data, has_version=True)
    assert data["status"] in ["SCHEDULED", "AUTHORIZED", "RELEASED", "VOIDED"]
    assert data["payee_type"] in ["AGENT", "MENTOR", "TEAM_LEAD", "REFERRAL", "CO_BROKE", "ROYALTY", "COMPANY"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_ledger_entry(data: dict):
    _assert_common(data, has_version=False)
    assert data["entry_type"] in [
        "FEE_SHORTFALL_ACCRUAL", "FEE_SHORTFALL_REVERSAL",
        "DEBIT_RECOVERY", "DEBIT_RECOVERY_REVERSAL",
        "MANUAL_DEBIT", "DEBIT_WRITE_OFF",
    ]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["resulting_balance_cents"], int)


def assert_tax_form(data: dict):
    _assert_common(data, has_version=True)
    assert data["status"] in ["DRAFT", "FINALIZED", "VOIDED"]
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["gross_paid_cents"], int)
    assert isinstance(data["accrual_gross_cents"], int)
    assert isinstance(data["filing_required"], bool)


def assert_trust_transaction(data: dict):
    _assert_common(data, has_version=False)
    assert data["kind"] in ["RECEIPT", "RECEIPT_REVERSAL", "RELEASE"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["trust_balance_after_cents"], int)
