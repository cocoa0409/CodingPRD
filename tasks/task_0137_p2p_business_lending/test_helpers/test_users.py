"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules — THREE roles are entity-backed and ONE is
opaque:

- PlatformOperator is OPAQUE. PRD §2.1: "PlatformOperator is an opaque
  operator role. When X-User-Role is PlatformOperator, X-User-ID is an
  opaque operator identifier not tied to any persisted entity; the
  server treats it as an audit handle and does not compare it to the id
  of any stored resource." Shared constants are canonical.

- ComplianceOfficer is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  ComplianceOfficer, X-User-ID is the id of the acting ComplianceOfficer
  record on the platform; ownership and segregation-of-duties checks
  compare this identifier to the persisted ComplianceOfficer."

- Borrower is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Borrower,
  X-User-ID is the id of the acting Borrower; ownership checks on any
  resource that references a Borrower (its listings, its loans,
  payments against those loans) compare the resource's borrower_id to
  X-User-ID."

- Investor is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Investor,
  X-User-ID is the id of the acting Investor; the server compares the
  resource's investor_id to X-User-ID on every investor-scoped read or
  write."

For ENTITY-BACKED roles the shared TEST_USERS fallback header is ONLY
safe for tests that do not exercise ownership (header-missing,
404-on-non-existent, role-mismatch, forbidden-on-other-borrower). Every
ownership-gated call MUST mint headers via
make_<role>_headers(<entity>["id"]) using the actual entity ids
returned by the create endpoints. Falling back to the shared constant
reproduces the canonical bug: the literal "fallback-..." id never
equals any real entity.id, so every ownership check rejects every
request, cascading "Setup failed" into dozens of tests.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifier — PRD §2.1.
# ---------------------------------------------------------------------------
PLATFORM_OPERATOR_ID = "operator-001"
PLATFORM_OPERATOR_ID_ALT = "operator-002"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
BORROWER_FALLBACK_ID = "fallback-borrower-1"
INVESTOR_FALLBACK_ID = "fallback-investor-1"
COMPLIANCE_OFFICER_FALLBACK_ID = "fallback-officer-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque PlatformOperator — shared constants are canonical.
    "platform_operator_headers": build_user_headers(
        PLATFORM_OPERATOR_ID, "PlatformOperator",
    ),
    "platform_operator_headers_alt": build_user_headers(
        PLATFORM_OPERATOR_ID_ALT, "PlatformOperator",
    ),
    # Entity-backed fallback headers — DO NOT use for ownership-gated
    # calls. Safe only for header-missing / role-mismatch /
    # 404-on-non-existent paths.
    "borrower_fallback_headers": build_user_headers(
        BORROWER_FALLBACK_ID, "Borrower",
    ),
    "investor_fallback_headers": build_user_headers(
        INVESTOR_FALLBACK_ID, "Investor",
    ),
    "compliance_officer_fallback_headers": build_user_headers(
        COMPLIANCE_OFFICER_FALLBACK_ID, "ComplianceOfficer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for every entity-backed role.
# ---------------------------------------------------------------------------
def make_platform_operator_headers(operator_id: str) -> Dict[str, str]:
    """For PlatformOperator (opaque). Any non-empty operator id is fine;
    this builder exists so tests that want a distinct operator id can
    supply one without relying on a single shared constant.

    PRD §2.1: "X-User-ID is an opaque operator identifier not tied to
    any persisted entity."
    """
    return build_user_headers(operator_id, "PlatformOperator")


def make_borrower_headers(borrower_id: str) -> Dict[str, str]:
    """For Borrower (entity_backed:Borrower). Pass the actual
    Borrower.id of the acting borrower.

    PRD §2.1: "When X-User-Role is Borrower, X-User-ID is the id of the
    acting Borrower; ownership checks on any resource that references a
    Borrower (its listings, its loans, payments against those loans)
    compare the resource's borrower_id to X-User-ID."

    Every Borrower-driven call whose success depends on owning the
    targeted resource MUST use this builder, not the shared
    BORROWER_FALLBACK_ID constant.
    """
    return build_user_headers(borrower_id, "Borrower")


def make_investor_headers(investor_id: str) -> Dict[str, str]:
    """For Investor (entity_backed:Investor). Pass the actual
    Investor.id of the acting investor.

    PRD §2.1: "When X-User-Role is Investor, X-User-ID is the id of the
    acting Investor; the server compares the resource's investor_id to
    X-User-ID on every investor-scoped read or write. An Investor may
    pledge only as themselves, and may read only their own
    investments."

    Every Investor-driven call (pledge, get own investment, list own
    investments) MUST use this builder, not the shared
    INVESTOR_FALLBACK_ID constant.
    """
    return build_user_headers(investor_id, "Investor")


def make_compliance_officer_headers(officer_id: str) -> Dict[str, str]:
    """For ComplianceOfficer (entity_backed:ComplianceOfficer). Pass
    the actual ComplianceOfficer.id of the acting officer.

    PRD §2.1: "When X-User-Role is ComplianceOfficer, X-User-ID is the
    id of the acting ComplianceOfficer record on the platform;
    ownership and segregation-of-duties checks compare this identifier
    to the persisted ComplianceOfficer."

    Every ComplianceOfficer call (approve, suspend, reinstate, ban,
    publish) MUST use this builder, not the shared
    COMPLIANCE_OFFICER_FALLBACK_ID constant — the implementation is
    free to require X-User-ID resolve to a persisted officer row.
    """
    return build_user_headers(officer_id, "ComplianceOfficer")


__all__ = [
    "PLATFORM_OPERATOR_ID",
    "PLATFORM_OPERATOR_ID_ALT",
    "BORROWER_FALLBACK_ID",
    "INVESTOR_FALLBACK_ID",
    "COMPLIANCE_OFFICER_FALLBACK_ID",
    "TEST_USERS",
    "make_platform_operator_headers",
    "make_borrower_headers",
    "make_investor_headers",
    "make_compliance_officer_headers",
]
