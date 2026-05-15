"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- RiskOfficer, ComplianceOfficer, SettlementOperator, MarketDataSystem all
  carry OPAQUE X-User-IDs. The server records them on AuditLog and on
  approver_user_id / filed_by_user_id but never compares them to any
  entity's id. Shared constants are canonical for these four roles.

- Trader is ENTITY-BACKED. PRD §2.1:
  "When `X-User-Role` is `Trader`, the supplied `X-User-ID` MUST be the
  `id` of an existing `Trader` row. Ownership checks on any resource that
  references a trader (`Limit`, `LimitAdjustmentRequest`, `Trade`,
  `Position`, `StopLossEvent`) compare the resource's `trader_id` foreign
  key to the caller's `X-User-ID`."

  Every ownership-gated Trader call MUST therefore use
  make_trader_headers(trader["id"]) — passing the shared
  TEST_USERS["trader_headers"] fallback would guarantee that ownership
  checks reject every real trader because the constant "trader-fallback"
  never equals any real Trader.id.

Segregation-of-duties (PRD §2.9 priority 5, §3.3) further requires that
the approver of a LimitAdjustmentRequest carry a DIFFERENT X-User-ID from
the trader who created the request — so we expose _alt variants for
opaque roles when a single test must drive two distinct actors.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and a non-binding Trader fallback.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # RiskOfficer (opaque)
    "risk_officer_headers": build_user_headers(
        "risk-officer-001", "RiskOfficer",
    ),
    "risk_officer_headers_alt": build_user_headers(
        "risk-officer-002", "RiskOfficer",
    ),
    "risk_officer_headers_alt2": build_user_headers(
        "risk-officer-003", "RiskOfficer",
    ),

    # ComplianceOfficer (opaque)
    "compliance_officer_headers": build_user_headers(
        "compliance-officer-001", "ComplianceOfficer",
    ),
    "compliance_officer_headers_alt": build_user_headers(
        "compliance-officer-002", "ComplianceOfficer",
    ),

    # SettlementOperator (opaque)
    "settlement_operator_headers": build_user_headers(
        "settlement-operator-001", "SettlementOperator",
    ),
    "settlement_operator_headers_alt": build_user_headers(
        "settlement-operator-002", "SettlementOperator",
    ),

    # MarketDataSystem (opaque)
    "market_data_headers": build_user_headers(
        "market-data-001", "MarketDataSystem",
    ),

    # Trader fallback — use ONLY for tests that do not exercise ownership
    # (missing-resource, wrong-role, raw input validation). PRD §2.1: a
    # real ownership-gated Trader call must use the actual Trader.id as
    # X-User-ID — see make_trader_headers below.
    "trader_headers": build_user_headers(
        "trader-fallback", "Trader",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — REQUIRED for the entity_backed Trader role.
# ---------------------------------------------------------------------------
def make_trader_headers(trader_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Trader, the supplied X-User-ID MUST be
    the id of an existing Trader row.' Pass the trader's id (returned by
    POST /fx-risk/traders) whenever the downstream call is ownership-gated
    (e.g., POST /fx-risk/limit-adjustments, POST /fx-risk/trades,
    POST /fx-risk/stop-loss/{id}/acknowledge).
    """
    return build_user_headers(trader_id, "Trader")


def make_risk_officer_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: RiskOfficer X-User-ID is opaque. Useful when a test needs a
    distinct officer id (e.g., approving a request the officer themselves
    created, segregation-of-duties scenarios)."""
    return build_user_headers(user_id, "RiskOfficer")


def make_compliance_officer_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: ComplianceOfficer X-User-ID is opaque."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_settlement_operator_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: SettlementOperator X-User-ID is opaque."""
    return build_user_headers(user_id, "SettlementOperator")


def make_market_data_headers(user_id: str) -> Dict[str, str]:
    """PRD §2.1: MarketDataSystem X-User-ID is opaque."""
    return build_user_headers(user_id, "MarketDataSystem")


__all__ = [
    "TEST_USERS",
    "make_trader_headers",
    "make_risk_officer_headers",
    "make_compliance_officer_headers",
    "make_settlement_operator_headers",
    "make_market_data_headers",
]
