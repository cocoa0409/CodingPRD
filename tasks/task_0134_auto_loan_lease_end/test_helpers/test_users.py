"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PlatformAdmin / LoanOfficer / FinanceManager / CollectionsAgent are
  OPAQUE. PRD §2.1: "The four operator roles — PlatformAdmin,
  LoanOfficer, FinanceManager, and CollectionsAgent — all carry an
  opaque identity. When X-User-Role is any of these four, X-User-ID is
  an opaque operator identifier not tied to any persisted entity; the
  server may record it for audit but does not compare it to any
  entity's id." Shared constants are canonical for these.

- Customer is ENTITY-BACKED. PRD §2.1: "The Customer role is
  entity-backed: when X-User-Role is Customer, X-User-ID is the id of
  the acting Customer, and ownership checks on any resource that
  references a Customer (loan contract, lease contract, payment,
  lease-end assessment, gap rider) compare the resource's customer_id
  to X-User-ID. In particular, a Customer calling pay on a payment
  whose parent contract's customer_id does not equal X-User-ID is
  treated as an unauthorized actor and rejected."

  Every Customer-acting call whose success depends on owning the
  targeted resource MUST mint headers via
  make_customer_headers(customer["id"]) — never via the shared
  CUSTOMER_FALLBACK_ID constant. Falling back to the shared constant
  for an entity-backed role reproduces the canonical bug: the literal
  "fallback-customer-1" never equals any real Customer.id, so every
  ownership check rejects every request regardless of implementation
  correctness.

The shared CUSTOMER_FALLBACK_ID constant is ONLY safe for tests that
DO NOT exercise ownership (header-missing, role-mismatch on a
non-existent resource, or 404 paths against unknown customers).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_ID: str = "platform-admin-001"
LOAN_OFFICER_ID: str = "loan-officer-001"
FINANCE_MANAGER_ID: str = "finance-manager-001"
COLLECTIONS_AGENT_ID: str = "collections-agent-001"

# Entity-backed fallback id — DO NOT use for ownership-gated Customer
# calls. Safe only for header-missing / role-mismatch / NotFound paths.
CUSTOMER_FALLBACK_ID: str = "fallback-customer-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque PlatformAdmin — shared constant is canonical.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_ID, "PlatformAdmin",
    ),
    # Opaque LoanOfficer — shared constant is canonical.
    "loan_officer_headers": build_user_headers(
        LOAN_OFFICER_ID, "LoanOfficer",
    ),
    # Opaque FinanceManager — shared constant is canonical.
    "finance_manager_headers": build_user_headers(
        FINANCE_MANAGER_ID, "FinanceManager",
    ),
    # Opaque CollectionsAgent — shared constant is canonical.
    "collections_agent_headers": build_user_headers(
        COLLECTIONS_AGENT_ID, "CollectionsAgent",
    ),
    # Entity-backed Customer fallback — DO NOT use for ownership-gated
    # calls. Safe only for header-missing / role-mismatch / 404 paths.
    "customer_fallback_headers": build_user_headers(
        CUSTOMER_FALLBACK_ID, "Customer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — REQUIRED for entity-backed Customer.
# The runtime Customer.id minted by POST /customers is the value the
# implementation will compare against in ownership checks.
# ---------------------------------------------------------------------------
def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """For Customer (entity_backed:Customer). Pass the actual
    Customer.id of the acting customer.

    PRD §2.1: "The Customer role is entity-backed: when X-User-Role is
    Customer, X-User-ID is the id of the acting Customer, and
    ownership checks on any resource that references a Customer (loan
    contract, lease contract, payment, lease-end assessment, gap
    rider) compare the resource's customer_id to X-User-ID."

    Every Customer-driven call whose success depends on owning the
    targeted resource MUST use this builder, not the shared
    CUSTOMER_FALLBACK_ID constant.
    """
    return build_user_headers(customer_id, "Customer")


def make_platform_admin_headers(operator_id: str) -> Dict[str, str]:
    """For PlatformAdmin (opaque). Any non-empty operator id works."""
    return build_user_headers(operator_id, "PlatformAdmin")


def make_loan_officer_headers(operator_id: str) -> Dict[str, str]:
    """For LoanOfficer (opaque)."""
    return build_user_headers(operator_id, "LoanOfficer")


def make_finance_manager_headers(operator_id: str) -> Dict[str, str]:
    """For FinanceManager (opaque)."""
    return build_user_headers(operator_id, "FinanceManager")


def make_collections_agent_headers(operator_id: str) -> Dict[str, str]:
    """For CollectionsAgent (opaque)."""
    return build_user_headers(operator_id, "CollectionsAgent")


__all__ = [
    "PLATFORM_ADMIN_ID",
    "LOAN_OFFICER_ID",
    "FINANCE_MANAGER_ID",
    "COLLECTIONS_AGENT_ID",
    "CUSTOMER_FALLBACK_ID",
    "TEST_USERS",
    "make_customer_headers",
    "make_platform_admin_headers",
    "make_loan_officer_headers",
    "make_finance_manager_headers",
    "make_collections_agent_headers",
]
