"""Pre-built role headers for every role in the PRD (§2.1).

Six roles are opaque: their `X-User-ID` is never compared against an entity
id, so shared constants are canonical for them. `CustomerRep` is bound to a
persisted `Customer` — for any ownership-gated call the caller MUST build
headers with the acting customer's id via `make_customer_rep_headers`.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "desk_admin_headers": build_user_headers("test-desk-admin-1", "DeskAdmin"),
    "trader_headers": build_user_headers("test-trader-1", "Trader"),
    "risk_officer_headers": build_user_headers("test-risk-officer-1", "RiskOfficer"),
    "quality_grader_headers": build_user_headers("test-quality-grader-1", "QualityGrader"),
    "warehouse_operator_headers": build_user_headers("test-warehouse-operator-1", "WarehouseOperator"),
    "claims_adjuster_headers": build_user_headers("test-claims-adjuster-1", "ClaimsAdjuster"),
}


def make_desk_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DeskAdmin")


def make_trader_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Trader")


def make_risk_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RiskOfficer")


def make_quality_grader_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "QualityGrader")


def make_warehouse_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WarehouseOperator")


def make_claims_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_customer_rep_headers(customer_id: str) -> dict:
    """CustomerRep is entity-backed: X-User-ID must be the acting Customer's id
    for every ownership-gated call (allocations, dock decisions, claims)."""
    return build_user_headers(customer_id, "CustomerRep")
