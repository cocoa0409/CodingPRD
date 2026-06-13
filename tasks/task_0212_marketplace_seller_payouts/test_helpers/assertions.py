"""Entity assertions and domain invariant checkers.

Built on the framework's generic format validators. Append-only entities
(LedgerEntry, BalanceStatement) carry only id + created_at — no updated_at,
no version (PRD §2.4).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    COUNTRY_CODES, TAX_CLASSIFICATIONS, PRODUCT_CATEGORIES, METHOD_TYPES, CURRENCIES,
)


def _assert_common(data: dict):
    """id + created_at + updated_at + version for common_fields:true entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_append_only_common(data: dict):
    """id + created_at only — no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_seller(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["country_code"] in COUNTRY_CODES
    assert data["tax_classification"] in TAX_CLASSIFICATIONS
    assert data["kyc_status"] in ["PENDING", "IN_REVIEW", "APPROVED", "REJECTED"]
    assert data["w9_status"] in ["NOT_SUBMITTED", "SUBMITTED", "APPROVED"]
    assert data["account_status"] in ["ONBOARDING", "ACTIVE", "SUSPENDED", "CLOSED"]
    assert data["risk_tier"] in ["STANDARD", "ELEVATED", "HIGH"]
    assert isinstance(data["seller_risk_score"], (int, float))
    assert 0 <= data["seller_risk_score"] <= 100
    for f in ("available_balance_cents", "pending_balance_cents", "reserve_held_cents",
              "ytd_gross_cents", "ytd_transaction_count"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_payout_method(data: dict):
    _assert_common(data)
    assert data["method_type"] in METHOD_TYPES
    assert data["currency"] in CURRENCIES
    assert data["verification_status"] in ["UNVERIFIED", "VERIFIED", "FAILED"]
    assert isinstance(data["is_default"], bool)


def assert_fee_schedule(data: dict):
    _assert_common(data)
    assert data["category"] in PRODUCT_CATEGORIES
    assert isinstance(data["commission_bps"], int)
    assert isinstance(data["maturation_days"], int)
    assert isinstance(data["is_active"], bool)


def assert_order(data: dict):
    _assert_common(data)
    assert data["category"] in PRODUCT_CATEGORIES
    assert isinstance(data["gross_amount_cents"], int) and data["gross_amount_cents"] >= 1
    assert data["settlement_status"] in ["PENDING", "AVAILABLE", "PAID"]
    assert data["clawback_status"] in ["NONE", "REFUND_CLAWED", "CHARGEBACK_CLAWED"]
    for f in ("commission_cents", "platform_fee_cents", "processing_fee_cents",
              "net_earnings_cents", "refunded_amount_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_ledger_entry(data: dict):
    _assert_append_only_common(data)
    assert "updated_at" not in data, "LedgerEntry is append-only; must not carry updated_at"
    assert "version" not in data, "LedgerEntry is append-only; must not carry version"
    assert data["source_type"] in [
        "ORDER_PROCEEDS", "REFUND_CLAWBACK", "CHARGEBACK_CLAWBACK", "CHARGEBACK_FEE",
        "RESERVE_HOLD", "RESERVE_RELEASE", "PAYOUT",
    ]
    assert data["hold_state"] in ["PENDING", "AVAILABLE", "REVERSED"]
    assert isinstance(data["amount_cents"], int)


def assert_reserve(data: dict):
    _assert_common(data)
    assert data["reserve_status"] in ["OPEN", "RELEASED"]
    assert isinstance(data["held_amount_cents"], int)


def assert_refund(data: dict):
    _assert_common(data)
    assert data["refund_status"] in ["REQUESTED", "APPLIED", "VOIDED"]
    assert data["reason"] in ["BUYER_REMORSE", "NOT_AS_DESCRIBED", "DAMAGED", "NOT_RECEIVED"]
    assert isinstance(data["refund_amount_cents"], int) and data["refund_amount_cents"] >= 1


def assert_chargeback(data: dict):
    _assert_common(data)
    assert data["chargeback_status"] in ["RECEIVED", "REPRESENTED", "WON", "LOST"]
    assert isinstance(data["dispute_fee_cents"], int)


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["dispute_status"] in [
        "FILED", "UNDER_REVIEW", "SELLER_RESPONDED", "GRANTED", "DENIED",
    ]
    assert data["claim_type"] in [
        "ITEM_NOT_RECEIVED", "ITEM_NOT_AS_DESCRIBED", "RETURN_NOT_REFUNDED",
    ]
    assert isinstance(data["response_round"], int) and data["response_round"] >= 0


def assert_payout(data: dict):
    _assert_common(data)
    assert data["payout_status"] in ["SCHEDULED", "RELEASED", "FAILED", "REVERSED"]
    for f in ("gross_available_cents", "reserve_withheld_cents", "payout_amount_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
    assert isinstance(data["order_ids"], list)


def assert_tax_form(data: dict):
    _assert_common(data)
    assert data["form_status"] in ["DRAFT", "ISSUED", "CORRECTED"]
    assert data["threshold_basis"] in ["FEDERAL_5000", "LEGACY_20K_200", "NONE"]
    assert isinstance(data["tax_year"], int)


def assert_balance_statement(data: dict):
    _assert_append_only_common(data)
    assert "updated_at" not in data, "BalanceStatement is append-only; must not carry updated_at"
    assert "version" not in data, "BalanceStatement is append-only; must not carry version"
    for f in ("opening_balance_cents", "closing_balance_cents", "total_credits_cents",
              "total_debits_cents", "total_payouts_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
