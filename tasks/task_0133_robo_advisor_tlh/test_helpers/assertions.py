"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract.

PRD §2.4: every persisted resource carries id + created_at +
updated_at + version EXCEPT RiskQuestionnaire, ModelPortfolio,
Security, CorrelationLink, WashSaleEvent, and DividendEvent which are
lean (id + created_at only).
"""
from __future__ import annotations

from typing import Any, Dict, Set

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'version is an integer that starts at 1 and increments
    by one on every mutation'."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got "
        f"{data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Client — PRD §3.1
# ---------------------------------------------------------------------------
def assert_client(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("birth_date"), str)
    assert data.get("kyc_status") in {"PENDING", "ACTIVE", "SUSPENDED"}
    risk = data.get("risk_band")
    assert risk is None or risk in {
        "CONSERVATIVE", "MODERATE", "AGGRESSIVE",
    }
    th = data.get("time_horizon_years")
    assert isinstance(th, int) and 1 <= th <= 40, (
        f"time_horizon_years must be int in [1,40], got {th!r}"
    )


# ---------------------------------------------------------------------------
# Account — PRD §3.3
# ---------------------------------------------------------------------------
def assert_account(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("client_id"), str)
    assert data.get("compliance_status") in {
        "ACTIVE", "FROZEN_DOC_REVIEW",
    }
    assert data.get("investment_status") in {
        "ACCUMULATING", "REBALANCING", "HARVESTING",
    }
    assert isinstance(data.get("cash_balance_cents"), int)
    assert data["cash_balance_cents"] >= 0
    drift = data.get("max_drift_pct")
    assert isinstance(drift, (int, float))


# ---------------------------------------------------------------------------
# RiskQuestionnaire — PRD §3.1
# ---------------------------------------------------------------------------
def assert_risk_questionnaire(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: 'both updated_at and version are absent on those rows'.
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "RiskQuestionnaire must NOT carry updated_at per PRD §2.4"
    )
    assert "version" not in data or data.get("version") is None, (
        "RiskQuestionnaire must NOT carry version per PRD §2.4"
    )
    assert isinstance(data.get("client_id"), str)
    for q in (
        "q1_loss_tolerance", "q2_volatility_comfort",
        "q3_growth_vs_stability", "q4_liquidity_need",
        "q5_experience",
    ):
        v = data.get(q)
        assert isinstance(v, int) and 1 <= v <= 5, (
            f"{q} must be int in [1,5], got {v!r}"
        )
    assert data.get("scoring_method") in {"STANDARD", "AGE_ADJUSTED"}
    assert isinstance(data.get("raw_score"), int)
    assert data.get("assigned_band") in {
        "CONSERVATIVE", "MODERATE", "AGGRESSIVE",
    }


# ---------------------------------------------------------------------------
# ModelPortfolio — PRD §3.2
# ---------------------------------------------------------------------------
def assert_model_portfolio(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert data.get("risk_band") in {
        "CONSERVATIVE", "MODERATE", "AGGRESSIVE",
    }
    assert data.get("horizon_band") in {"SHORT", "MID", "LONG"}
    ta = data.get("target_allocation")
    assert isinstance(ta, dict), "target_allocation must be a mapping"
    expected_classes = {
        "US_EQUITY", "INTL_EQUITY", "US_BOND", "INTL_BOND", "CASH",
    }
    assert set(ta.keys()) == expected_classes, (
        f"target_allocation keys must be the five fixed asset classes; "
        f"got {set(ta.keys())}"
    )
    for cls, w in ta.items():
        assert isinstance(w, (int, float)), (
            f"weight for {cls} must be numeric, got {w!r}"
        )
        assert 0.0 <= float(w) <= 1.0
    total = sum(float(v) for v in ta.values())
    assert abs(total - 1.0) < 1e-6, (
        f"target_allocation weights must sum to 1.000, got {total!r}"
    )
    assert isinstance(data.get("is_active"), bool)


# ---------------------------------------------------------------------------
# Security — PRD §3.9
# ---------------------------------------------------------------------------
def assert_security(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    ticker = data.get("ticker")
    assert isinstance(ticker, str) and 1 <= len(ticker) <= 10, (
        f"ticker must be 1..10 chars, got {ticker!r}"
    )
    assert ticker.isupper(), (
        f"ticker must be uppercase, got {ticker!r}"
    )
    assert data.get("asset_class") in {
        "US_EQUITY", "INTL_EQUITY", "US_BOND", "INTL_BOND", "CASH",
    }
    assert isinstance(data.get("substantially_identical_group_id"), str)
    assert isinstance(data.get("is_investable"), bool)
    assert isinstance(data.get("last_price_cents"), int)
    assert data["last_price_cents"] >= 0


# ---------------------------------------------------------------------------
# CorrelationLink — PRD §3.9
# ---------------------------------------------------------------------------
def assert_correlation_link(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert isinstance(data.get("security_a_id"), str)
    assert isinstance(data.get("security_b_id"), str)
    c = data.get("correlation")
    assert isinstance(c, (int, float)) and -1.0 <= float(c) <= 1.0


# ---------------------------------------------------------------------------
# Position — PRD §3.4
# ---------------------------------------------------------------------------
def assert_position(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("account_id"), str)
    assert isinstance(data.get("security_id"), str)
    assert isinstance(data.get("shares"), (int, float))
    assert isinstance(data.get("total_cost_basis_cents"), int)
    assert isinstance(data.get("market_value_cents"), int)


# ---------------------------------------------------------------------------
# Lot — PRD §3.4
# ---------------------------------------------------------------------------
def assert_lot(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("position_id"), str)
    assert isinstance(data.get("buy_trade_id"), str)
    assert is_iso8601_timestamp(data.get("acquired_at", ""))
    assert isinstance(data.get("shares_opened"), (int, float))
    assert isinstance(data.get("shares_remaining"), (int, float))
    assert isinstance(data.get("unit_cost_cents"), int)
    assert isinstance(data.get("adjusted_unit_cost_cents"), int)
    assert data.get("status") in {
        "OPEN", "PARTIALLY_CLOSED", "CLOSED",
    }


# ---------------------------------------------------------------------------
# Trade — PRD §3.4
# ---------------------------------------------------------------------------
def assert_trade(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("account_id"), str)
    assert isinstance(data.get("security_id"), str)
    assert data.get("side") in {"BUY", "SELL"}
    assert isinstance(data.get("requested_shares"), (int, float))
    assert float(data["requested_shares"]) > 0
    assert data.get("status") in {
        "PENDING", "EXECUTED", "SETTLED", "CANCELLED", "REJECTED",
    }


# ---------------------------------------------------------------------------
# HarvestOpportunity — PRD §3.7
# ---------------------------------------------------------------------------
def assert_harvest_opportunity(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("account_id"), str)
    assert isinstance(data.get("position_id"), str)
    assert isinstance(data.get("unrealized_loss_cents"), int)
    assert data.get("status") in {
        "DETECTED", "APPROVED", "EXECUTED", "DISMISSED", "BLOCKED",
    }
    assert is_iso8601_timestamp(data.get("detected_at", ""))


# ---------------------------------------------------------------------------
# RebalanceRun — PRD §3.8
# ---------------------------------------------------------------------------
def assert_rebalance_run(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("account_id"), str)
    qk = data.get("quarter_key")
    assert isinstance(qk, str) and len(qk) == 7 and qk[4] == "-" \
        and qk[5] == "Q", (
        f"quarter_key must match 'YYYY-Qn', got {qk!r}"
    )
    assert data.get("status") in {
        "SCHEDULED", "IN_PROGRESS", "COMPLETED",
        "BLOCKED_BY_WASH_SALE", "FAILED",
    }


# ---------------------------------------------------------------------------
# Form1099B — PRD §3.11
# ---------------------------------------------------------------------------
def assert_form_1099b(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("client_id"), str)
    ty = data.get("tax_year")
    assert isinstance(ty, int)
    assert data.get("status") in {"DRAFT", "ISSUED", "VOIDED"}
    for f in (
        "short_term_proceeds_cents",
        "short_term_cost_basis_cents",
        "short_term_realized_gain_loss_cents",
        "long_term_proceeds_cents",
        "long_term_cost_basis_cents",
        "long_term_realized_gain_loss_cents",
        "total_disallowed_wash_sale_cents",
    ):
        assert isinstance(data.get(f), int), (
            f"{f} must be int (cents), got {data.get(f)!r}"
        )


# ---------------------------------------------------------------------------
# WashSaleEvent — PRD §3.6
# ---------------------------------------------------------------------------
def assert_wash_sale_event(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert isinstance(data.get("sell_trade_id"), str)
    assert isinstance(data.get("replacement_trade_id"), str)
    assert isinstance(data.get("group_id"), str)
    assert isinstance(data.get("matched_shares"), (int, float))
    assert isinstance(data.get("disallowed_loss_cents"), int)
    assert isinstance(data.get("replacement_lot_id"), str)
    assert is_iso8601_timestamp(data.get("recorded_at", ""))


# ---------------------------------------------------------------------------
# DividendEvent — PRD §3.10
# ---------------------------------------------------------------------------
def assert_dividend_event(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    assert isinstance(data.get("account_id"), str)
    assert isinstance(data.get("security_id"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert data["amount_cents"] > 0
    assert is_iso8601_timestamp(data.get("received_at", ""))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(before: Dict[str, Any],
                                      after: Dict[str, Any]) -> None:
    """PRD §2.4: 'version increments by one on every mutation'."""
    assert "version" in before and "version" in after
    assert after["version"] == before["version"] + 1, (
        f"version must advance by 1: before={before['version']} "
        f"after={after['version']}"
    )


def assert_round_half_up_cents(value: Any) -> None:
    """PRD §2.8: monetary amounts are integer cents."""
    assert isinstance(value, int), (
        f"monetary value must be integer cents, got {value!r}"
    )


__all__ = [
    "assert_client",
    "assert_account",
    "assert_risk_questionnaire",
    "assert_model_portfolio",
    "assert_security",
    "assert_correlation_link",
    "assert_position",
    "assert_lot",
    "assert_trade",
    "assert_harvest_opportunity",
    "assert_rebalance_run",
    "assert_form_1099b",
    "assert_wash_sale_event",
    "assert_dividend_event",
    "assert_version_incremented_by_one",
    "assert_round_half_up_cents",
]
