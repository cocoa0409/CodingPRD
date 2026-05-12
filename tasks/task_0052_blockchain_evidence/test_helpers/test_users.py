"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Customer is ENTITY-BACKED. 'When X-User-Role is Customer, X-User-ID is
  the id of the acting Customer; ownership checks on any resource that
  references a Customer (Evidence, Batch, Recharge, Invoice, and read
  access on owned Certificate, JudicialPackage, and TimestampNotarization
  rows) compare the resource's customer_id (or, for indirect references,
  the customer_id of the linked Evidence) to X-User-ID.' Every
  ownership-gated Customer-role call MUST use make_customer_headers(
  customer['id']) — passing a shared fallback constant guarantees the
  ownership check fails for any real customer id, cascading 'Setup
  failed' into every downstream test.

- NotaryOfficer, JudicialOfficer, PlatformAdmin all carry OPAQUE
  X-User-IDs. 'The server may record it on AuditLog.actor_id but never
  compares it to any entity's id.' Shared constants are safe for these
  roles.

The fallback Customer constant in TEST_USERS is ONLY for tests that do
not exercise ownership: missing-headers / wrong-role / missing-resource
calls. Any test that invokes an ownership-gated endpoint MUST switch to
make_customer_headers(customer['id']).
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared opaque-role constants and a non-binding Customer fallback.
# ---------------------------------------------------------------------------
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — canonical constants.
    "platform_admin_headers": build_user_headers(
        "platform-admin-001", "PlatformAdmin",
    ),
    "platform_admin_headers_alt": build_user_headers(
        "platform-admin-002", "PlatformAdmin",
    ),
    "notary_officer_headers": build_user_headers(
        "notary-officer-001", "NotaryOfficer",
    ),
    "judicial_officer_headers": build_user_headers(
        "judicial-officer-001", "JudicialOfficer",
    ),
    "judicial_officer_headers_alt": build_user_headers(
        "judicial-officer-002", "JudicialOfficer",
    ),
    # Customer fallback — use ONLY for tests that do not exercise
    # ownership. Per PRD §2.1 the real X-User-ID must equal Customer.id
    # for any ownership-gated call; the per-instance builder below is
    # the correct path in fixtures.
    "customer_headers": build_user_headers(
        "customer-fallback", "Customer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders. Required for the entity_backed Customer role.
# ---------------------------------------------------------------------------
def make_customer_headers(customer_id: str) -> Dict[str, str]:
    """PRD §2.1: 'When X-User-Role is Customer, X-User-ID is the id of
    the acting Customer.' Pass the actual Customer.id returned by
    POST /customers whenever the downstream call is ownership-gated."""
    return build_user_headers(customer_id, "Customer")


def make_platform_admin_headers(admin_id: str = "platform-admin-001"
                                 ) -> Dict[str, str]:
    """PRD §2.1: PlatformAdmin X-User-ID is an opaque operator id."""
    return build_user_headers(admin_id, "PlatformAdmin")


def make_notary_officer_headers(officer_id: str = "notary-officer-001"
                                 ) -> Dict[str, str]:
    """PRD §2.1: NotaryOfficer X-User-ID is an opaque operator id."""
    return build_user_headers(officer_id, "NotaryOfficer")


def make_judicial_officer_headers(officer_id: str = "judicial-officer-001"
                                   ) -> Dict[str, str]:
    """PRD §2.1: JudicialOfficer X-User-ID is an opaque operator id."""
    return build_user_headers(officer_id, "JudicialOfficer")


__all__ = [
    "TEST_USERS",
    "make_customer_headers",
    "make_platform_admin_headers",
    "make_notary_officer_headers",
    "make_judicial_officer_headers",
]
