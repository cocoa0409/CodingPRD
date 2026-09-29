"""Entity assertions, precision helpers and domain invariant checkers."""

from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    MONEY_TOLERANCE,
    PCT_TOLERANCE,
    PRICE_TOLERANCE,
    SHARE_TOLERANCE,
)


# ------------------------------------------------------------ precision helpers
def money(expected: float):
    """Dollar amounts are carried to exactly 2 decimal places."""
    return pytest.approx(expected, abs=MONEY_TOLERANCE)


def shares(expected: float):
    """Share quantities are carried to exactly 3 decimal places."""
    return pytest.approx(expected, abs=SHARE_TOLERANCE)


def price(expected: float):
    """Prices per share are carried to exactly 4 decimal places."""
    return pytest.approx(expected, abs=PRICE_TOLERANCE)


def pct(expected: float):
    """Percentages are carried to 4 decimal places as decimal fractions."""
    return pytest.approx(expected, abs=PCT_TOLERANCE)


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 timestamp, got {value!r}"
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected_iso: str, label: str = "timestamp"):
    """Assert two ISO 8601 UTC timestamps denote the same instant."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected {label} {expected_iso}, got {actual}"
    )


# ------------------------------------------------------------- common audit fields
def assert_common_fields(data: dict, entity_name: str = "resource"):
    """id, created_at, updated_at and version as the PRD describes them."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a server-minted UUID"
    assert "_" not in str(data.get("id", "")), f"{entity_name}.id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1"
    )


# --------------------------------------------------------------- entity assertions
def assert_fund(data: dict):
    assert_common_fields(data, "Fund")
    assert isinstance(data["name"], str) and 0 < len(data["name"]) <= 120
    assert isinstance(data["fund_family_code"], str) and 0 < len(data["fund_family_code"]) <= 12
    assert data["status"] in ("ACTIVE", "CLOSED_TO_NEW")
    assert isinstance(data["cutoff_time_utc"], str)


def assert_share_class(data: dict):
    assert_common_fields(data, "ShareClass")
    assert data["class_code"] in ("A", "B", "C", "I")
    assert data["seed_nav_per_share"] > 0
    assert isinstance(data["breakpoint_tiers"], list) and len(data["breakpoint_tiers"]) >= 1
    assert data["breakpoint_tiers"][0]["min_qualifying_amount"] == 0
    previous = None
    for tier in data["breakpoint_tiers"]:
        assert 0 <= tier["load_pct"] <= 0.0850
        if previous is not None:
            assert tier["min_qualifying_amount"] > previous
        previous = tier["min_qualifying_amount"]
    assert isinstance(data["cdsc_enabled"], bool)
    assert data["total_shares_outstanding"] >= 0


def assert_shareholder_account(data: dict):
    assert_common_fields(data, "ShareholderAccount")
    assert data["registration_type"] in (
        "INDIVIDUAL", "JOINT_TENANTS", "UGMA_UTMA",
        "IRA_TRADITIONAL", "ROTH_IRA", "TRUST", "CORPORATE",
    )
    assert data["account_channel"] in ("DIRECT", "NETWORKED", "OMNIBUS")
    assert data["status"] in ("PENDING_DOCS", "ACTIVE", "RESTRICTED", "CLOSED")
    assert data["dividend_option"] in ("CASH", "REINVEST")
    assert data["household_basis_variant"] in ("MARKET_VALUE_BASIS", "HISTORICAL_COST_BASIS")
    assert isinstance(data["tin_certified"], bool)
    assert len(data["state_code"]) == 2 and data["state_code"].isupper()
    assert data["household_basis_amount"] >= 0


def assert_position(data: dict):
    assert_common_fields(data, "Position")
    assert data["shares"] >= 0, "a share balance may never be negative"
    assert data["cost_basis_amount"] >= 0
    assert data["reinvested_shares"] >= 0
    assert data["avg_cost_per_share"] >= 0
    assert data["market_value_amount"] >= 0
    assert data["current_roa_tier_pct"] >= 0


def assert_nav_record(data: dict):
    assert_common_fields(data, "NavRecord")
    assert data["status"] in (
        "PRELIMINARY", "FINAL", "UNDER_ERROR_REVIEW", "CORRECTED", "STALE_REPRICE_REQUIRED",
    )
    assert data["nav_per_share"] > 0, "a struck NAV must be greater than zero"
    assert data["total_net_assets"] >= 0
    assert data["shares_outstanding_snapshot"] >= 0


def assert_trade(data: dict):
    assert_common_fields(data, "Trade")
    assert data["trade_type"] in ("PURCHASE", "REDEMPTION", "EXCHANGE", "REINVESTMENT")
    assert data["execution_status"] in (
        "RECEIVED", "PENDING_AS_OF_APPROVAL", "PRICED_PROVISIONAL",
        "PRICED_FINAL", "RESTATED", "CANCELLED",
    )
    assert data["settlement_status"] in ("UNSETTLED", "SETTLED", "REVERSED")
    assert is_iso8601_timestamp(data.get("received_at", "")), "received_at must be ISO 8601"
    assert isinstance(data["trade_date"], str) and len(data["trade_date"]) == 10


def assert_distribution(data: dict):
    assert_common_fields(data, "Distribution")
    assert data["distribution_type"] in (
        "ORDINARY_INCOME", "SHORT_TERM_CAPITAL_GAIN", "LONG_TERM_CAPITAL_GAIN",
    )
    assert data["status"] in ("DECLARED", "RECORDED", "PAID", "REVERSED")
    assert data["rate_per_share"] > 0
    assert isinstance(data["payment_count"], int) and data["payment_count"] >= 0


def assert_distribution_payment(data: dict):
    assert_common_fields(data, "DistributionPayment")
    assert data["status"] in ("PENDING", "PAID", "REVERSED")
    assert data["payout_option"] in ("CASH", "REINVEST")
    assert data["shares_of_record"] > 0
    assert data["net_amount"] == money(data["gross_amount"] - data["withholding_amount"])


def assert_systematic_plan(data: dict):
    assert_common_fields(data, "SystematicPlan")
    assert data["plan_type"] in (
        "SYSTEMATIC_INVESTMENT", "SYSTEMATIC_WITHDRAWAL", "SYSTEMATIC_EXCHANGE",
    )
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["frequency"] in ("MONTHLY", "QUARTERLY")
    assert data["amount"] > 0
    assert isinstance(data["executed_count"], int) and data["executed_count"] >= 0


def assert_blue_sky_registration(data: dict):
    assert_common_fields(data, "BlueSkyRegistration")
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED")
    assert data["registered_amount"] > 0
    assert data["remaining_amount"] >= 0, "remaining capacity may never be negative"
    assert_registration_capacity_identity(data)


def assert_pricing_error_case(data: dict):
    assert_common_fields(data, "PricingErrorCase")
    assert data["status"] in (
        "DETECTED", "ASSESSED", "IMMATERIAL_CLOSED",
        "MATERIAL_APPROVED", "REPROCESSED", "SUPERSEDED",
    )
    assert data["corrected_nav_per_share"] > 0
    assert data["original_nav_per_share"] > 0
    if data.get("materiality") is not None:
        assert data["materiality"] in ("MATERIAL", "IMMATERIAL")
    assert isinstance(data["restated_trade_count"], int)
    assert isinstance(data["invalidated_nav_record_count"], int)


def assert_omnibus_reconciliation(data: dict):
    assert_common_fields(data, "OmnibusReconciliation")
    assert data["status"] in ("MATCHED", "BREAK_IDENTIFIED", "RESOLVED", "DISPUTED")
    assert data["dealer_reported_purchase_amount"] >= 0
    assert data["dealer_reported_redemption_amount"] >= 0
    assert data["tolerance_amount"] >= 0


def assert_share_ledger_entry(data: dict):
    """A ledger entry carries only id and created_at besides its own fields."""
    assert is_valid_uuid(data.get("id", "")), "ShareLedgerEntry.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "ShareLedgerEntry.created_at must be an ISO 8601 UTC timestamp"
    )
    assert data.get("updated_at") is None, (
        "an append-only share ledger entry has no updated_at field"
    )
    assert data.get("version") is None, (
        "an append-only share ledger entry has no version field"
    )
    assert data["share_delta"] != 0, "a share_delta is never exactly zero"
    assert data["entry_reason"] in (
        "PURCHASE_SETTLEMENT", "REDEMPTION_SETTLEMENT", "EXCHANGE_OUT", "EXCHANGE_IN",
        "DIVIDEND_REINVESTMENT", "NAV_CORRECTION_RESTATEMENT",
        "TRADE_REVERSAL", "DISTRIBUTION_REVERSAL",
    )


# ------------------------------------------------------------ domain invariants
def assert_registration_capacity_identity(registration: dict):
    """registered_amount == remaining_amount + reserved_amount + consumed_amount."""
    total = (
        registration["remaining_amount"]
        + registration["reserved_amount"]
        + registration["consumed_amount"]
    )
    assert total == money(registration["registered_amount"]), (
        f"capacity identity broken: registered {registration['registered_amount']} != "
        f"remaining {registration['remaining_amount']} + reserved "
        f"{registration['reserved_amount']} + consumed {registration['consumed_amount']}"
    )


def assert_registration_capacity(registration: dict, reserved: float,
                                 consumed: float, remaining: float, status: str):
    """Assert the whole three-way capacity split plus the resulting posture."""
    assert registration["reserved_amount"] == money(reserved)
    assert registration["consumed_amount"] == money(consumed)
    assert registration["remaining_amount"] == money(remaining)
    assert registration["status"] == status
    assert_registration_capacity_identity(registration)


def assert_position_balances(position: dict, expected_shares: float,
                             expected_cost_basis: float = None):
    assert position["shares"] == shares(expected_shares)
    if expected_cost_basis is not None:
        assert position["cost_basis_amount"] == money(expected_cost_basis)


def assert_trade_state(trade: dict, execution_status: str, settlement_status: str):
    assert trade["execution_status"] == execution_status, (
        f"Expected execution_status {execution_status}, got {trade['execution_status']}"
    )
    assert trade["settlement_status"] == settlement_status, (
        f"Expected settlement_status {settlement_status}, got {trade['settlement_status']}"
    )


def assert_pricing_fields_cleared(trade: dict):
    """The reprocessing sweep clears every pricing field back to null."""
    for field in (
        "pricing_variant", "nav_per_share_applied", "sales_load_pct", "sales_load_amount",
        "net_invested_amount", "shares_transacted", "roa_qualifying_amount",
        "roa_basis_variant",
    ):
        assert trade.get(field) is None, f"expected {field} cleared to null, got {trade[field]}"
