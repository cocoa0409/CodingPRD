"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

- Regulator: X-User-ID is an opaque operator identifier not tied to any
  persisted entity. The shared TEST_USERS constant is canonical.

- Enterprise: entity-backed on Enterprise. PRD §2.1: 'When X-User-Role is
  Enterprise, X-User-ID is the id of the acting Enterprise entity.
  Ownership checks on any resource that references an Enterprise (such as
  EmissionReport, ComplianceDeclaration, PenaltyOrder, TradingOrder,
  Allocation, or AnnualSettlement via its enterprise_id field) compare
  the resource's foreign-key reference to X-User-ID.' Ownership-gated
  calls MUST use make_enterprise_headers(enterprise_id) with the actual
  Enterprise.id.

- VerifierAgency: opaque operator identifier, but ownership-gated against
  VerificationAssignment.agency_id for the complete-onsite and
  issue-report endpoints. Use make_verifier_agency_headers(agency_id)
  where agency_id matches the VerificationAssignment.agency_id stored at
  assign-verifier time.
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants. For Regulator (opaque) this is canonical. For
# Enterprise (entity-backed) and VerifierAgency (opaque-but-ownership-gated)
# the constant is a fallback for non-ownership tests; ownership-gated
# tests must call make_enterprise_headers(enterprise_id) /
# make_verifier_agency_headers(agency_id).
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque Regulator — canonical.
    "regulator_headers": build_user_headers("regulator-001", "Regulator"),
    "regulator_headers_alt": build_user_headers("regulator-002", "Regulator"),

    # Enterprise fallback — used only for tests that don't exercise the
    # enterprise-id ownership comparison (e.g., RBAC ERR_FORBIDDEN where
    # the role itself is rejected before ownership is examined).
    "enterprise_headers": build_user_headers(
        "enterprise-fallback-001", "Enterprise"
    ),

    # VerifierAgency fallback — used only for tests that don't depend on
    # the agency_id ownership comparison.
    "verifier_agency_headers": build_user_headers(
        "agency-fallback-001", "VerifierAgency"
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders
# ---------------------------------------------------------------------------
def make_regulator_headers(
    regulator_id: str = "regulator-001",
) -> Dict[str, str]:
    """Regulator headers; identity is opaque per PRD §2.1."""
    return build_user_headers(regulator_id, "Regulator")


def make_enterprise_headers(enterprise_id: str) -> Dict[str, str]:
    """Enterprise headers. PRD §2.1: 'When X-User-Role is Enterprise,
    X-User-ID is the id of the acting Enterprise entity. Ownership checks
    on any resource that references an Enterprise ... compare the resource's
    foreign-key reference to X-User-ID.'

    Pass the actual Enterprise.id whenever the call is ownership-gated
    (which is every Enterprise-exclusive endpoint except RBAC negative
    tests).
    """
    return build_user_headers(enterprise_id, "Enterprise")


def make_verifier_agency_headers(agency_id: str) -> Dict[str, str]:
    """VerifierAgency headers. PRD §2.1: 'When X-User-Role is
    VerifierAgency, X-User-ID is likewise an opaque operator identifier;
    for verification-assignment operations it must equal the agency_id
    recorded on the VerificationAssignment, which is how the server
    constrains a verifier to act only on its own assignments.'

    Pass the same string used as agency_id when the assignment was created.
    """
    return build_user_headers(agency_id, "VerifierAgency")


__all__ = [
    "TEST_USERS",
    "make_regulator_headers",
    "make_enterprise_headers",
    "make_verifier_agency_headers",
]
