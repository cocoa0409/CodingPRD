"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Customer is ENTITY-BACKED. PRD §2.1:
  "When X-User-Role is Customer, X-User-ID is the id of the acting
  Customer; ownership checks on any resource that references a Customer
  (directly through customer_id, or transitively through
  Account.customer_id) compare the resource's owning customer chain to
  X-User-ID. A customer who attempts to read or mutate a resource that
  does not chain back to their own Customer.id is rejected with
  ERR_OWNERSHIP_VIOLATION at HTTP 403."

  Every Customer-acting call whose success depends on owning the
  targeted resource MUST mint headers via
  make_customer_headers(customer["id"]) — never via the shared
  CUSTOMER_FALLBACK_ID constant. Falling back to the shared constant
  reproduces the canonical bug: the literal "fallback-customer-1"
  never equals any real Customer.id, so every ownership check rejects
  every request as ERR_OWNERSHIP_VIOLATION, cascading "Setup failed"
  into dozens of tests.

- ComplianceOfficer and PlatformAdmin are OPAQUE operator identities.
  PRD §2.1: "When X-User-Role is ComplianceOfficer or PlatformAdmin,
  X-User-ID is an opaque operator identifier not tied to any persisted
  entity; the server may record it for audit purposes but does not
  compare it to any entity's id, and these roles are not subject to the
  ownership check."
  Shared constants are canonical for these operator-only roles.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
COMPLIANCE_OFFICER_ID = "compliance-001"
COMPLIANCE_OFFICER_ID_ALT = "compliance-002"

PLATFORM_ADMIN_ID = "admin-001"

# Entity-backed Customer fallback id — DO NOT use for ownership-gated
# calls.
CUSTOMER_FALLBACK_ID = "fallback-customer-1"

# A second Customer fallback id used for ERR_OWNERSHIP_VIOLATION tests
# (acts as a customer that demonstrably is NOT the owner).
CUSTOMER_OTHER_ID = "fallback-customer-other"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque ComplianceOfficer — shared constant is canonical.
    "compliance_headers": build_user_headers(
        COMPLIANCE_OFFICER_ID, "ComplianceOfficer",
    ),
    "compliance_headers_alt": build_user_headers(
        COMPLIANCE_OFFICER_ID_ALT, "ComplianceOfficer",
    ),
    # Opaque PlatformAdmin — shared constant is canonical.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_ID, "PlatformAdmin",
    ),
    # Entity-backed Customer fallback — DO NOT use for ownership-gated
    # calls. Safe only for header-missing / role-mismatch / 404-on-
    # non-existent / ownership-violation negative paths.
    "customer_fallback_headers": build_user_headers(
        CUSTOMER_FALLBACK_ID, "Customer",
    ),
    "customer_other_headers": build_user_headers(
        CUSTOMER_OTHER_ID, "Customer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Customer.
# The runtime Customer.id minted by POST /brokerage/customers is the
# value the implementation will compare against in ownership checks
# (directly through customer_id, transitively through
# Account.customer_id, and through chained references on KYCSubmission,
# OptionsApproval, Order, ACATTransfer). PRD §2.1.
# ---------------------------------------------------------------------------
def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """For Customer (entity_backed:Customer). Pass the actual
    Customer.id of the acting customer.

    PRD §2.1: "When X-User-Role is Customer, X-User-ID is the id of the
    acting Customer; ownership checks on any resource that references a
    Customer ... compare the resource's owning customer chain to
    X-User-ID."

    Every Customer-driven call whose success depends on owning the
    targeted resource MUST use this builder, not the shared
    CUSTOMER_FALLBACK_ID constant.
    """
    return build_user_headers(customer_id, "Customer")


def make_compliance_headers(officer_id: str) -> Dict[str, str]:
    """For ComplianceOfficer (opaque). Any non-empty operator id is
    fine; this builder exists so tests that want a distinct id (for
    audit-token discrimination or two-officer race tests) can supply one
    without relying on a single shared constant."""
    return build_user_headers(officer_id, "ComplianceOfficer")


def make_platform_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlatformAdmin (opaque)."""
    return build_user_headers(admin_id, "PlatformAdmin")


__all__ = [
    "COMPLIANCE_OFFICER_ID",
    "COMPLIANCE_OFFICER_ID_ALT",
    "PLATFORM_ADMIN_ID",
    "CUSTOMER_FALLBACK_ID",
    "CUSTOMER_OTHER_ID",
    "TEST_USERS",
    "make_customer_headers",
    "make_compliance_headers",
    "make_platform_admin_headers",
]
