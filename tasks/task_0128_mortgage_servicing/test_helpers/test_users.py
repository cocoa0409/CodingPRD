"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Borrower is ENTITY-BACKED. PRD §2.1:
  "Borrower is an entity-backed identity: when X-User-Role is Borrower,
  X-User-ID is the id of the acting Borrower. Ownership checks on any
  resource that references a Borrower (directly on Loan, transitively
  through Loan for Payment, EscrowAnalysis, Disbursement, ForbearancePlan,
  PmiRemovalRequest, ForeclosureCase, and MediationCase) compare the
  resource's borrower_id ... to X-User-ID. A borrower who attempts to
  operate on a loan whose borrower_id does not equal their X-User-ID is
  treated as forbidden (ERR_FORBIDDEN)."

  Every Borrower-acting call whose success depends on owning the
  targeted resource MUST mint headers via
  make_borrower_headers(borrower["id"]) — never via the shared
  BORROWER_FALLBACK_ID constant. Falling back to the shared constant
  reproduces the canonical bug: the literal "fallback-borrower-1" never
  equals any real Borrower.id, so every ownership check rejects every
  request as ERR_FORBIDDEN, cascading "Setup failed" into dozens of
  tests.

- Servicer, LossMitigationUnderwriter, PmiUnderwriter,
  ForeclosureAttorney, and PlatformAdmin are OPAQUE operator identities.
  PRD §2.1: "The remaining five roles ... are opaque operator identities
  not tied to any persisted entity. For these roles, X-User-ID is
  recorded for audit but is never compared to a resource's id."
  Shared constants are canonical for these operator-only roles.

SEGREGATION OF DUTIES — PRD §2.1: "a single X-User-ID cannot both
extend a mediation offer and accept the same offer on the same
MediationCase". Two distinct operator ids per role let tests model a
clean (non-equal) operator pair for normal flows and a deliberately
equal id for ERR_SEGREGATION_OF_DUTIES assertions.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
SERVICER_ID = "servicer-001"
SERVICER_ID_ALT = "servicer-002"

LMU_ID = "lmu-001"
LMU_ID_ALT = "lmu-002"

PMI_UNDERWRITER_ID = "pmi-001"
PMI_UNDERWRITER_ID_ALT = "pmi-002"

FORECLOSURE_ATTORNEY_ID = "atty-001"
FORECLOSURE_ATTORNEY_ID_ALT = "atty-002"

PLATFORM_ADMIN_ID = "admin-001"

# Entity-backed fallback id — DO NOT use for ownership-gated calls.
BORROWER_FALLBACK_ID = "fallback-borrower-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque Servicer — shared constant is canonical.
    "servicer_headers": build_user_headers(SERVICER_ID, "Servicer"),
    "servicer_headers_alt": build_user_headers(
        SERVICER_ID_ALT, "Servicer",
    ),
    # Opaque LossMitigationUnderwriter — shared constant is canonical.
    "lmu_headers": build_user_headers(LMU_ID, "LossMitigationUnderwriter"),
    "lmu_headers_alt": build_user_headers(
        LMU_ID_ALT, "LossMitigationUnderwriter",
    ),
    # Opaque PmiUnderwriter — shared constant is canonical.
    "pmi_underwriter_headers": build_user_headers(
        PMI_UNDERWRITER_ID, "PmiUnderwriter",
    ),
    "pmi_underwriter_headers_alt": build_user_headers(
        PMI_UNDERWRITER_ID_ALT, "PmiUnderwriter",
    ),
    # Opaque ForeclosureAttorney — shared constant is canonical.
    "foreclosure_attorney_headers": build_user_headers(
        FORECLOSURE_ATTORNEY_ID, "ForeclosureAttorney",
    ),
    "foreclosure_attorney_headers_alt": build_user_headers(
        FORECLOSURE_ATTORNEY_ID_ALT, "ForeclosureAttorney",
    ),
    # Opaque PlatformAdmin — shared constant is canonical.
    "platform_admin_headers": build_user_headers(
        PLATFORM_ADMIN_ID, "PlatformAdmin",
    ),
    # Entity-backed Borrower fallback — DO NOT use for ownership-gated
    # calls. Safe only for header-missing / role-mismatch /
    # 404-on-non-existent / forbidden-on-other-borrower paths.
    "borrower_fallback_headers": build_user_headers(
        BORROWER_FALLBACK_ID, "Borrower",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Borrower.
# The runtime Borrower.id minted by POST /borrowers is the value the
# implementation will compare against in ownership checks
# (Loan.borrower_id, and transitively through Loan for Payment,
# EscrowAnalysis, Disbursement, ForbearancePlan, PmiRemovalRequest,
# ForeclosureCase, MediationCase). PRD §2.1.
# ---------------------------------------------------------------------------
def make_borrower_headers(borrower_id: str) -> Dict[str, str]:
    """For Borrower (entity_backed:Borrower). Pass the actual
    Borrower.id of the acting borrower.

    PRD §2.1: "when X-User-Role is Borrower, X-User-ID is the id of the
    acting Borrower. Ownership checks on any resource that references a
    Borrower ... compare the resource's borrower_id ... to X-User-ID."

    Every Borrower-driven call whose success depends on owning the
    targeted resource MUST use this builder, not the shared
    BORROWER_FALLBACK_ID constant.
    """
    return build_user_headers(borrower_id, "Borrower")


def make_servicer_headers(servicer_id: str) -> Dict[str, str]:
    """For Servicer (opaque). Any non-empty operator id is fine; this
    builder exists so tests that want a distinct servicer id (for
    audit-token discrimination or two-servicer race tests) can supply
    one without relying on a single shared constant."""
    return build_user_headers(servicer_id, "Servicer")


def make_lmu_headers(lmu_id: str) -> Dict[str, str]:
    """For LossMitigationUnderwriter (opaque). Distinct ids per call
    enable segregation-of-duties tests (PRD §3.7: "the underwriter who
    extended the most recent offer must not be the same X-User-ID that
    accepted it")."""
    return build_user_headers(lmu_id, "LossMitigationUnderwriter")


def make_pmi_underwriter_headers(pmi_id: str) -> Dict[str, str]:
    """For PmiUnderwriter (opaque)."""
    return build_user_headers(pmi_id, "PmiUnderwriter")


def make_foreclosure_attorney_headers(atty_id: str) -> Dict[str, str]:
    """For ForeclosureAttorney (opaque)."""
    return build_user_headers(atty_id, "ForeclosureAttorney")


def make_platform_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlatformAdmin (opaque)."""
    return build_user_headers(admin_id, "PlatformAdmin")


__all__ = [
    "SERVICER_ID",
    "SERVICER_ID_ALT",
    "LMU_ID",
    "LMU_ID_ALT",
    "PMI_UNDERWRITER_ID",
    "PMI_UNDERWRITER_ID_ALT",
    "FORECLOSURE_ATTORNEY_ID",
    "FORECLOSURE_ATTORNEY_ID_ALT",
    "PLATFORM_ADMIN_ID",
    "BORROWER_FALLBACK_ID",
    "TEST_USERS",
    "make_borrower_headers",
    "make_servicer_headers",
    "make_lmu_headers",
    "make_pmi_underwriter_headers",
    "make_foreclosure_attorney_headers",
    "make_platform_admin_headers",
]
