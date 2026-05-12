"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

  - PlatformAdmin, ProductOperator, ComplianceReviewer, NavOperator, and
    ClearingOperator are all OPAQUE: 'X-User-ID is an opaque operator
    identifier not tied to any persisted entity.' Shared constants are
    canonical for these five roles.

  - Investor is ENTITY-BACKED: 'X-User-ID is the id of the acting Investor
    entity; ownership checks on any resource that references an Investor
    (such as an Order, a Holding, or a DividendDistribution) compare the
    resource's investor_id field to X-User-ID.' Tests that issue an
    Investor-scoped call MUST mint headers via make_investor_headers()
    with the actual Investor.id; using the shared TEST_USERS["investor_headers"]
    constant for an ownership-gated call would only pass if the
    implementation skipped the check.

PRD §2.10 priority 6/7/8 plus PRD §3.2 / §3.4 / §3.7 require segregation of
duties between several pairs of operator IDs:

  - shelf creator (ProductOperator who submits) vs shelf approver
    (ComplianceReviewer)  -- PRD §3.2
  - NAV publisher (NavOperator) vs Fund.shelf_review_actor_id
    (the ComplianceReviewer who approved the shelf)  -- PRD §3.4
  - reconciliation creator (ClearingOperator who opens the run) vs
    reconciliation closer  -- PRD §3.7

To make these checks resolvable we provide DISTINCT operator IDs for each
role, plus an extra second-instance (e.g., compliance_reviewer_alt) for
tests that must pit two ComplianceReviewers against each other.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. All operator roles in this PRD are opaque (PRD §2.1),
# so the shared constants are canonical for them. The Investor entry is a
# fallback for tests that don't exercise ownership comparison.
TEST_USERS: Dict[str, Dict[str, str]] = {
    # PlatformAdmin -- opaque (PRD §2.1)
    "platform_admin_headers": build_user_headers(
        "platform-admin-001", "PlatformAdmin"
    ),
    # ProductOperator -- opaque, but locked onto Fund.shelf_creator_actor_id
    # at submit-for-review time (PRD §3.2). Two distinct IDs are useful for
    # tests that need a second operator (e.g., re-submit after rejection).
    "product_operator_headers": build_user_headers(
        "product-op-001", "ProductOperator"
    ),
    "product_operator_headers_alt": build_user_headers(
        "product-op-002", "ProductOperator"
    ),
    # ComplianceReviewer -- opaque, but locked onto Fund.shelf_review_actor_id
    # at approve-shelf time (PRD §3.2 / §3.4). Two distinct IDs are required
    # to test SoD pairs (creator vs approver, NAV publisher vs reviewer).
    "compliance_reviewer_headers": build_user_headers(
        "compliance-001", "ComplianceReviewer"
    ),
    "compliance_reviewer_headers_alt": build_user_headers(
        "compliance-002", "ComplianceReviewer"
    ),
    # NavOperator -- opaque, but compared against Fund.shelf_review_actor_id
    # for the NAV-publisher SoD check (PRD §3.4).
    "nav_operator_headers": build_user_headers(
        "nav-op-001", "NavOperator"
    ),
    "nav_operator_headers_alt": build_user_headers(
        "nav-op-002", "NavOperator"
    ),
    # ClearingOperator -- opaque, but compared against the run's recorded
    # creator for the closer SoD check (PRD §3.7).
    "clearing_operator_headers": build_user_headers(
        "clearing-op-001", "ClearingOperator"
    ),
    "clearing_operator_headers_alt": build_user_headers(
        "clearing-op-002", "ClearingOperator"
    ),
    # Investor -- entity-backed (PRD §2.1). Only safe for tests that do
    # NOT exercise ownership comparison (404 / forbidden / schema tests).
    # Ownership-gated calls MUST use make_investor_headers(investor_id).
    "investor_headers_fallback": build_user_headers(
        "investor-fallback-not-a-real-id", "Investor"
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders
# ---------------------------------------------------------------------------
def make_investor_headers(investor_id: str) -> Dict[str, str]:
    """Investor headers (entity_backed:Investor per PRD §2.1).

    Pass the actual Investor.id of the acting investor. Required for any
    call that PRD §2.1 says is ownership-checked: POST /orders,
    POST /orders/{id}/cancel,
    POST /dividend-plans/{id}/distributions/{investor_id}/set-option,
    GET /investors/{self_id}, GET /investors/{self_id}/holdings.
    """
    return build_user_headers(investor_id, "Investor")


def make_platform_admin_headers(admin_id: str = "platform-admin-001") -> Dict[str, str]:
    return build_user_headers(admin_id, "PlatformAdmin")


def make_product_operator_headers(operator_id: str) -> Dict[str, str]:
    """ProductOperator headers with a custom operator id.

    PRD §3.2 stamps this id onto Fund.shelf_creator_actor_id at
    submit-for-review time, locking the SoD comparison."""
    return build_user_headers(operator_id, "ProductOperator")


def make_compliance_reviewer_headers(reviewer_id: str) -> Dict[str, str]:
    """ComplianceReviewer headers with a custom reviewer id.

    PRD §3.2 stamps this id onto Fund.shelf_review_actor_id at
    approve-shelf time, which is then compared against the NAV publisher's
    X-User-ID for the §3.4 NAV SoD check."""
    return build_user_headers(reviewer_id, "ComplianceReviewer")


def make_nav_operator_headers(operator_id: str) -> Dict[str, str]:
    """NavOperator headers with a custom operator id.

    PRD §3.4: 'the operator's X-User-ID must differ from the fund's
    Fund.shelf_review_actor_id (otherwise ERR_SOD_VIOLATION_NAV).'"""
    return build_user_headers(operator_id, "NavOperator")


def make_clearing_operator_headers(operator_id: str) -> Dict[str, str]:
    """ClearingOperator headers with a custom operator id.

    PRD §3.7: 'The closer's X-User-ID must differ from the run's recorded
    creator (otherwise ERR_SOD_VIOLATION_RECON).'"""
    return build_user_headers(operator_id, "ClearingOperator")


__all__ = [
    "TEST_USERS",
    "make_investor_headers",
    "make_platform_admin_headers",
    "make_product_operator_headers",
    "make_compliance_reviewer_headers",
    "make_nav_operator_headers",
    "make_clearing_operator_headers",
]
