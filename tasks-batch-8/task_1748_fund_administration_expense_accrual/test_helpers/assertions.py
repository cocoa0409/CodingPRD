"""Entity assertions and domain invariant checkers (PRD §2.5, §2.6, §3)."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

# Money is 2dp half-up (PRD §2.6); tolerance well under one cent.
MONEY_ABS = 1e-4
# Per-share figures are 4dp half-up (PRD §2.6); tolerance well under 0.0001.
RATE_ABS = 1e-6


def assert_money(actual, expected, label="value"):
    assert actual == pytest.approx(expected, abs=MONEY_ABS), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_rate(actual, expected, label="value"):
    assert actual == pytest.approx(expected, abs=RATE_ABS), (
        f"{label}: expected {expected}, got {actual}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_fund(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fund_name"], str) and data["fund_name"]
    assert isinstance(data["ticker"], str) and data["ticker"]
    assert data["base_currency"] in ["USD", "EUR", "GBP"]
    assert isinstance(data["fiscal_year_end"], str)
    assert isinstance(data["adviser_name"], str)
    assert data["admin_fee_bps"] > 0
    assert isinstance(data["adviser_fee_tiers"], list) and data["adviser_fee_tiers"]
    assert data["day_count_convention"] in ["ACT_365", "ACT_360"]
    assert "last_closed_fiscal_year_end" in data


def assert_share_class(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["fund_id"])
    assert isinstance(data["class_ticker"], str) and data["class_ticker"]
    assert data["distribution_frequency"] in [
        "DAILY",
        "MONTHLY",
        "QUARTERLY",
        "ANNUALLY",
    ]
    assert isinstance(data["shares_outstanding"], (int, float))
    assert isinstance(data["retained_income"], (int, float))


def assert_security(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["security_identifier"], str)
    assert data["asset_class"] in [
        "EQUITY",
        "FIXED_INCOME",
        "CASH_EQUIVALENT",
        "DERIVATIVE",
    ]
    assert data["default_pricing_level"] in ["LEVEL_1", "LEVEL_2", "LEVEL_3"]
    assert data["currency"] in ["USD", "EUR", "GBP"]


def assert_position(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["share_class_id"])
    assert is_valid_uuid(data["security_id"])
    assert isinstance(data["quantity"], (int, float))
    assert isinstance(data["cost_basis_total"], (int, float))
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_price_observation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["security_id"])
    assert isinstance(data["price_date"], str)
    assert data["price"] > 0
    assert data["source"] in [
        "EXCHANGE_CLOSE",
        "PRICING_SERVICE",
        "BROKER_QUOTE",
        "FAIR_VALUE_COMMITTEE",
    ]
    assert data["pricing_level"] in ["LEVEL_1", "LEVEL_2", "LEVEL_3"]
    assert isinstance(data["is_fair_value_override"], bool)
    assert data["status"] in ["SUBMITTED", "APPROVED", "OVERRIDDEN"]


def assert_nav_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["share_class_id"])
    assert isinstance(data["accounting_date"], str)
    assert data["status"] in ["ESTIMATED", "FINAL", "REOPENED"]
    assert data["pricing_variant_used"] in ["PROVISIONAL", "FINAL_PRICED"]
    assert isinstance(data["gross_asset_value"], (int, float))
    assert isinstance(data["expense_accrual_total"], (int, float))
    assert isinstance(data["total_net_assets"], (int, float))
    assert isinstance(data["nav_per_share"], (int, float))
    assert "provisional_nav_per_share" in data
    assert "final_nav_per_share" in data
    assert isinstance(data["created_by_user_id"], str)


def assert_expense_accrual(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["share_class_id"])
    assert isinstance(data["accrual_date"], str)
    assert data["category"] in [
        "ADMIN_FEE",
        "CUSTODY_FEE",
        "AUDIT_FEE",
        "LEGAL_FEE",
        "OTHER",
    ]
    assert data["annual_rate_bps"] > 0
    assert isinstance(data["base_net_assets"], (int, float))
    assert isinstance(data["accrued_amount"], (int, float))
    assert data["status"] in ["ESTIMATED", "POSTED"]


def assert_waiver_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["share_class_id"])
    assert data["cap_bps"] > 0
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    assert 1 <= data["recovery_window_months"] <= 36
    assert data["status"] in ["ACTIVE", "EXPIRED"]
    assert isinstance(data["recoverable_balance"], (int, float))


def assert_waiver_ledger_entry(data: dict):
    # Append-only: id + created_at exist; updated_at and version are absent (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "ledger entries must not expose updated_at"
    assert "version" not in data, "ledger entries must not expose version"
    assert is_valid_uuid(data["waiver_agreement_id"])
    assert data["entry_type"] in ["WAIVER", "RECOUPMENT"]
    assert data["amount"] > 0
    assert isinstance(data["entry_date"], str)
    assert "expires_at" in data
    assert isinstance(data["remaining_amount"], (int, float))


def assert_distribution(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["share_class_id"])
    for field in ("declaration_date", "ex_date", "record_date", "payable_date"):
        assert isinstance(data[field], str)
    assert isinstance(data["distributable_amount"], (int, float))
    assert isinstance(data["shares_snapshot"], (int, float))
    assert isinstance(data["income_per_share"], (int, float))
    assert isinstance(data["total_amount"], (int, float))
    assert data["status"] in ["DECLARED", "PAID", "CANCELLED"]
    assert "reinvested_shares" in data
    assert "paid_at" in data


def assert_reconciliation_break(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["fund_id"])
    assert is_valid_uuid(data["position_id"])
    assert data["break_type"] in ["CUSTODIAN_POSITION", "BROKER_POSITION"]
    assert isinstance(data["break_date"], str)
    assert data["counterparty_quantity"] >= 0
    assert isinstance(data["book_quantity"], (int, float))
    assert isinstance(data["variance"], (int, float))
    assert "resolution_type" in data
    assert "prior_book_quantity" in data
    assert data["status"] in ["OPEN", "ESCALATED", "RESOLVED"]


def assert_fee_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["fund_id"])
    assert data["fee_type"] in ["ADVISER", "ADMINISTRATOR"]
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["average_daily_net_assets"], (int, float))
    assert isinstance(data["gross_fee"], (int, float))
    assert isinstance(data["waiver_offset"], (int, float))
    assert isinstance(data["net_fee"], (int, float))
    assert data["status"] in ["DRAFT", "APPROVED", "PAID"]
    assert isinstance(data["created_by_user_id"], str)
    assert "approved_by_user_id" in data


def assert_regulatory_filing(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["fund_id"])
    assert data["filing_type"] in [
        "N_PORT",
        "N_CEN",
        "ANNUAL_REPORT",
        "SEMI_ANNUAL_REPORT",
    ]
    assert isinstance(data["period_end"], str)
    assert isinstance(data["filing_deadline"], str)
    assert data["status"] in [
        "DRAFT",
        "PENDING_REVIEW",
        "APPROVED",
        "FILED",
        "AMENDED",
    ]
    assert "filed_at" in data
    assert isinstance(data["filed_after_deadline"], bool)
    assert isinstance(data["prepared_by_user_id"], str)
    assert "approved_by_user_id" in data


def assert_nav_invariants(data: dict):
    """Domain invariants that must hold for any accounting record (PRD §3.4)."""
    assert_money(
        data["total_net_assets"],
        data["gross_asset_value"] - data["expense_accrual_total"],
        "total_net_assets == gross_asset_value - expense_accrual_total",
    )
    assert data["expense_accrual_total"] >= 0
