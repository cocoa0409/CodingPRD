"""Entity assertions and domain invariant checkers.

These helpers validate the shape and field types of response payloads
against PRD §2.4 (common-fields contract) and PRD §3.x (entity-specific
contracts). They use the framework's generic checks (is_valid_uuid,
is_iso8601_timestamp) for primitive types.

The TypedDicts in test_helpers.types use total=False because PRD entities
expose different subsets in different lifecycle states (e.g., a SUBMITTED
order has no confirmed_amount_cents yet); the assert_* helpers here are
the strict-shape validator that tests use to pin the per-state contract.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import AUDIT_ACTIONS


# ---------------------------------------------------------------------------
# Common-fields contract (PRD §2.4)
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: every common-fields entity exposes id (UUID), created_at,
    updated_at, version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1 and only grows"


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: NavSnapshot/LotEntry/DividendDistribution/
    ReconciliationException/SettlementInstruction/AuditLog carry only
    id + created_at; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    # PRD §2.4: these entities do NOT expose updated_at / version. We do
    # not assert their absence (PRD doesn't forbid it explicitly), but we
    # never read them.


# ---------------------------------------------------------------------------
# Investor (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_investor(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["investor_type"] in ("INDIVIDUAL", "INSTITUTIONAL")
    assert isinstance(data["country_code"], str)
    assert data["risk_tolerance"] in ("C1", "C2", "C3", "C4", "C5")
    assert data["tax_resident_status"] in ("DOMESTIC", "FOREIGN", "EXEMPT")
    assert data["kyc_status"] in ("PENDING", "APPROVED", "REJECTED")
    assert isinstance(data["bank_account_number"], str)
    assert isinstance(data["cash_balance_cents"], int)
    assert data["cash_balance_cents"] >= 0


# ---------------------------------------------------------------------------
# Fund (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_fund(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["fund_code"], str) and len(data["fund_code"]) == 6
    assert data["fund_code"].isdigit(), (
        "fund_code must match ^[0-9]{6}$ per PRD §3.2"
    )
    assert data["fund_type"] in (
        "EQUITY", "BOND", "HYBRID", "MONEY_MARKET", "QDII",
    )
    assert data["risk_rating"] in ("R1", "R2", "R3", "R4", "R5")
    assert isinstance(data["allowed_country_codes"], list)
    assert data["status"] in (
        "DRAFT", "UNDER_REVIEW", "ON_SHELF", "SUSPENDED", "OFF_SHELF",
    )
    for fee_field in (
        "management_fee_bps_annual",
        "custodian_fee_bps_annual",
        "sales_service_fee_bps_annual",
        "conversion_fee_bps",
        "large_redemption_threshold_pct_bps",
    ):
        assert isinstance(data[fee_field], int)
    assert isinstance(data["subscription_fee_tiers"], list)
    assert isinstance(data["redemption_fee_tiers"], list)
    assert isinstance(data["back_end_load_enabled"], bool)
    assert isinstance(data["min_subscription_amount_cents"], int)
    # max_subscription_amount_cents may be null
    assert isinstance(data["min_redemption_shares"], int)
    assert isinstance(data["total_outstanding_shares"], int)
    assert data["total_outstanding_shares"] >= 0


# ---------------------------------------------------------------------------
# NAV snapshot (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_nav_snapshot(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert data["status"] in ("PROVISIONAL", "PUBLISHED", "ADJUSTED")
    assert isinstance(data["fund_id"], str)
    for cents_field in (
        "gross_assets_cents",
        "management_fee_accrued_cents",
        "custodian_fee_accrued_cents",
        "sales_service_fee_accrued_cents",
        "net_assets_cents",
    ):
        assert isinstance(data[cents_field], int), (
            f"{cents_field} must be integer cents per PRD §2.6"
        )
    assert isinstance(data["shares_outstanding_at_nav"], int)
    assert data["shares_outstanding_at_nav"] >= 0
    assert isinstance(data["nav_per_share_micros"], int)
    assert data["nav_per_share_micros"] >= 0


# ---------------------------------------------------------------------------
# Order (PRD §3.3, §3.4)
# ---------------------------------------------------------------------------
def assert_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["fund_id"], str)
    assert isinstance(data["investor_id"], str)
    assert data["order_type"] in ("SUBSCRIBE", "REDEEM", "CONVERT")
    assert data["status"] in (
        "SUBMITTED", "ACCEPTED", "CONFIRMED", "REJECTED",
        "CANCELLED", "LARGE_REDEMPTION_DEFERRED",
    )
    assert isinstance(data["idempotency_key"], str)


def assert_order_confirmed(data: Dict[str, Any]) -> None:
    """PRD §3.4 / §3.5: a CONFIRMED order carries
    confirmed_nav_per_share_micros, confirmed_shares,
    confirmed_amount_cents."""
    assert_order(data)
    assert data["status"] == "CONFIRMED"
    assert isinstance(data["confirmed_nav_per_share_micros"], int)
    assert data["confirmed_nav_per_share_micros"] > 0
    assert isinstance(data["confirmed_shares"], int)
    assert data["confirmed_shares"] >= 0
    assert isinstance(data["confirmed_amount_cents"], int)


# ---------------------------------------------------------------------------
# Holding (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_holding(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["investor_id"], str)
    assert isinstance(data["fund_id"], str)
    assert isinstance(data["shares"], int) and data["shares"] >= 0
    assert isinstance(data["cost_basis_cents"], int) and data["cost_basis_cents"] >= 0


# ---------------------------------------------------------------------------
# DividendPlan / DividendDistribution (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_dividend_plan(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["fund_id"], str)
    assert data["status"] in ("ANNOUNCED", "EX_DIVIDEND", "PAID", "CANCELLED")
    for date_field in (
        "announcement_date", "record_date", "ex_dividend_date", "payment_date",
    ):
        assert isinstance(data[date_field], str), f"{date_field} must be string"
    assert isinstance(data["dividend_per_share_micros"], int)
    assert isinstance(data["tax_rate_bps_domestic"], int)
    assert isinstance(data["tax_rate_bps_foreign"], int)


def assert_dividend_distribution(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data["dividend_plan_id"], str)
    assert isinstance(data["investor_id"], str)
    assert isinstance(data["eligible_shares"], int)
    assert isinstance(data["gross_dividend_cents"], int)
    assert isinstance(data["tax_withheld_cents"], int)
    assert isinstance(data["net_dividend_cents"], int)
    assert data["option"] in ("CASH", "REINVEST")
    assert isinstance(data["reinvested_shares"], int)
    # PRD §3.6: net = gross - tax (exact integer arithmetic)
    assert (
        data["net_dividend_cents"]
        == data["gross_dividend_cents"] - data["tax_withheld_cents"]
    ), "net_dividend_cents must equal gross_dividend_cents - tax_withheld_cents"


# ---------------------------------------------------------------------------
# Reconciliation (PRD §3.7)
# ---------------------------------------------------------------------------
def assert_reconciliation_run(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert data["scope"] in ("TA_VS_CUSTODIAN", "TA_VS_CHANNEL", "TA_VS_BANK")
    assert data["status"] in (
        "OPEN", "EXCEPTIONS_FOUND", "RESOLVED", "CLOSED",
    )
    assert isinstance(data["total_internal_amount_cents"], int)
    assert isinstance(data["total_external_amount_cents"], int)
    assert isinstance(data["net_break_cents"], int)


def assert_reconciliation_exception(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert data["kind"] in (
        "MISSING_INTERNAL", "MISSING_EXTERNAL",
        "AMOUNT_MISMATCH", "SHARE_MISMATCH",
    )
    assert data["resolution_status"] in ("OPEN", "ADJUSTED", "WAIVED")


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.8, §3.8)
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    assert_append_only_fields(data)
    assert isinstance(data["actor_user_id"], str)
    assert isinstance(data["actor_role"], str)
    assert data["action"] in AUDIT_ACTIONS, (
        f"PRD §2.8: action must be one of {AUDIT_ACTIONS}, got {data.get('action')!r}"
    )
    assert isinstance(data["subject_entity"], str)
    assert isinstance(data["subject_id"], str)


# ---------------------------------------------------------------------------
# Clock (PRD §2.12)
# ---------------------------------------------------------------------------
def assert_clock(data: Dict[str, Any]) -> None:
    assert data.get("id") == "clock", (
        f"PRD §2.4: Clock has fixed id 'clock', got {data.get('id')!r}"
    )
    assert isinstance(data["now"], str)
    assert is_iso8601_timestamp(data["now"]), "Clock.now must be ISO 8601"


# ---------------------------------------------------------------------------
# Audit-log helpers
# ---------------------------------------------------------------------------
def find_audit_entries(
    rows: Iterable[Dict[str, Any]],
    *,
    action: Optional[str] = None,
    subject_entity: Optional[str] = None,
    subject_id: Optional[str] = None,
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
):
    """Return rows matching every supplied filter (case-sensitive)."""
    out = []
    for row in rows:
        if action is not None and row.get("action") != action:
            continue
        if subject_entity is not None and row.get("subject_entity") != subject_entity:
            continue
        if subject_id is not None and row.get("subject_id") != subject_id:
            continue
        if from_state is not None and row.get("from_state") != from_state:
            continue
        if to_state is not None and row.get("to_state") != to_state:
            continue
        out.append(row)
    return out


__all__ = [
    "assert_common_fields",
    "assert_append_only_fields",
    "assert_investor",
    "assert_fund",
    "assert_nav_snapshot",
    "assert_order",
    "assert_order_confirmed",
    "assert_holding",
    "assert_dividend_plan",
    "assert_dividend_distribution",
    "assert_reconciliation_run",
    "assert_reconciliation_exception",
    "assert_audit_log",
    "assert_clock",
    "find_audit_entries",
]
