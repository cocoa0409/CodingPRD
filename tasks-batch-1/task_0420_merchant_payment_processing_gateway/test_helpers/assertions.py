"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_ONBOARDING_STATUSES = {"PENDING_REVIEW", "APPROVED", "REJECTED", "SUSPENDED"}
_RISK_BANDS = {"LOW", "MEDIUM", "HIGH"}
_PAYOUT_METHODS = {"BANK_ACCOUNT", "DEBIT_CARD"}
_PRICING_MODELS = {"FLAT", "INTERCHANGE_PLUS"}
_AUTH_STATUSES = {"AUTHORIZED", "CAPTURED", "VOIDED", "EXPIRED"}
_SETTLEMENT_STATUSES = {"PENDING", "BATCHED", "SETTLED", "REVERSED"}
_REFUND_STATUSES = {"PENDING", "SETTLED", "FAILED"}
_REFUND_REASONS = {"REQUESTED_BY_CUSTOMER", "DUPLICATE", "FRAUDULENT"}
_DISPUTE_STATUSES = {"OPEN", "UNDER_REVIEW", "REPRESENTED", "WON", "LOST", "ACCEPTED"}
_BATCH_STATUSES = {"OPEN", "SETTLED", "FUNDED"}
_PAYOUT_STATUSES = {"REQUESTED", "PAID", "RETURNED"}
_RESERVE_STATUSES = {"HELD", "RELEASED"}
_RISK_DECISIONS = {"OPEN", "APPROVED", "REJECTED"}
_LEDGER_ACCOUNTS = {"AVAILABLE", "RESERVE"}
_LEDGER_ENTRY_TYPES = {
    "FUNDING", "FEE", "REFUND", "CHARGEBACK", "CHARGEBACK_REVERSAL",
    "RESERVE_HOLD", "RESERVE_RELEASE", "PAYOUT", "PAYOUT_RETURN", "ADJUSTMENT",
}
_LEDGER_SOURCE_TYPES = {
    "CHARGE", "REFUND", "DISPUTE", "SETTLEMENT_BATCH", "RESERVE_ENTRY", "PAYOUT", "MANUAL",
}


def _assert_common_full(data: dict):
    """Full first-class resource: id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1+, got {data['version']}"


def _assert_common_append_only(data: dict):
    """Append-only audit record: ONLY id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry a version field"
    assert "updated_at" not in data, "append-only record must not carry an updated_at field"


def assert_merchant(data: dict):
    _assert_common_full(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["mcc"], str)
    assert data["onboarding_status"] in _ONBOARDING_STATUSES
    assert data["risk_band"] is None or data["risk_band"] in _RISK_BANDS
    assert isinstance(data["requested_monthly_volume_cents"], int)
    assert isinstance(data["reserve_rate_bps"], int)
    assert isinstance(data["funding_delay_days"], int)
    assert isinstance(data["available_balance_cents"], int)
    assert isinstance(data["reserved_balance_cents"], int)
    assert data["payout_method"] in _PAYOUT_METHODS


def assert_fee_plan(data: dict):
    _assert_common_full(data)
    assert isinstance(data["name"], str)
    assert data["pricing_model"] in _PRICING_MODELS
    assert isinstance(data["chargeback_fee_cents"], int)


def assert_charge(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data["merchant_id"])
    assert isinstance(data["auth_amount_cents"], int)
    assert isinstance(data["captured_amount_cents"], int)
    assert isinstance(data["refunded_amount_cents"], int)
    assert isinstance(data["processing_fee_cents"], int)
    assert data["auth_status"] in _AUTH_STATUSES
    assert data["settlement_status"] in _SETTLEMENT_STATUSES
    assert data["settlement_batch_id"] is None or is_valid_uuid(data["settlement_batch_id"])
    assert isinstance(data["card_last4"], str)


def assert_refund(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data["charge_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["refund_status"] in _REFUND_STATUSES
    assert data["reason"] in _REFUND_REASONS


def assert_dispute(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data["charge_id"])
    assert isinstance(data["disputed_amount_cents"], int)
    assert data["dispute_status"] in _DISPUTE_STATUSES
    assert isinstance(data["representment_round"], int)
    assert isinstance(data["chargeback_fee_cents"], int)


def assert_settlement_batch(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data["merchant_id"])
    assert isinstance(data["business_date"], str)
    assert data["batch_status"] in _BATCH_STATUSES
    for field in ("gross_captured_cents", "total_fees_cents", "total_refunds_cents",
                  "reserve_held_cents", "net_funding_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_payout(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data["merchant_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["payout_status"] in _PAYOUT_STATUSES
    assert isinstance(data["scheduled_for"], str)


def assert_reserve_entry(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data["merchant_id"])
    assert is_valid_uuid(data["settlement_batch_id"])
    assert isinstance(data["amount_cents"], int)
    assert data["reserve_status"] in _RESERVE_STATUSES


def assert_tax_1099k(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data["merchant_id"])
    assert isinstance(data["tax_year"], int)
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["transaction_count"], int)
    assert isinstance(data["reportable"], bool)


def assert_risk_review(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data["merchant_id"])
    assert data["decision"] in _RISK_DECISIONS
    assert data["assigned_risk_band"] is None or data["assigned_risk_band"] in _RISK_BANDS


def assert_ledger_entry(data: dict):
    _assert_common_append_only(data)
    assert is_valid_uuid(data["merchant_id"])
    assert data["account"] in _LEDGER_ACCOUNTS
    assert isinstance(data["amount_cents"], int)
    assert data["entry_type"] in _LEDGER_ENTRY_TYPES
    assert data["source_type"] in _LEDGER_SOURCE_TYPES


def assert_webhook_event(data: dict):
    _assert_common_append_only(data)
    assert is_valid_uuid(data["merchant_id"])


def assert_balances_nonnegative_reserve(merchant: dict):
    """Domain invariant: reserved_balance_cents is always >= 0 by construction."""
    assert merchant["reserved_balance_cents"] >= 0, (
        f"reserved_balance_cents must never be negative, got {merchant['reserved_balance_cents']}"
    )
