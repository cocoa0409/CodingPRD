"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Borrower is ENTITY-BACKED. PRD §2.1: "When the acting role is
  Borrower, the value of X-User-ID is the id of the acting Borrower;
  any borrower-scoped read (such as fetching a borrower, property,
  senior lien, HELOC, or any of its child collections) compares the
  resource's owning borrower chain to X-User-ID and rejects mismatches
  with ERR_FORBIDDEN."

  Every Borrower-acting call whose success depends on owning the
  targeted resource MUST mint headers via
  make_borrower_headers(borrower["id"]) — never via the shared
  BORROWER_FALLBACK_ID constant. Falling back to the shared constant
  reproduces the canonical bug: the literal string never equals any
  real Borrower.id, so every ownership check rejects every request
  as ERR_FORBIDDEN, cascading "Setup failed" into dozens of tests.

- Originator, Servicer, PlatformAdmin are OPAQUE operator identities.
  PRD §2.1: "When the acting role is Originator, Servicer, or
  PlatformAdmin, X-User-ID is an opaque operator identifier that is
  not tied to any persisted entity; the server may record or log it,
  but does not compare it to any entity's id." Shared constants are
  canonical for these operator-only roles.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
ORIGINATOR_ID = "originator-001"
ORIGINATOR_ID_ALT = "originator-002"

SERVICER_ID = "servicer-001"
SERVICER_ID_ALT = "servicer-002"

PLATFORM_ADMIN_ID = "admin-001"

# Entity-backed fallback id — DO NOT use for ownership-gated calls.
BORROWER_FALLBACK_ID = "fallback-borrower-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque Originator — shared constant is canonical.
    "originator_headers": build_user_headers(ORIGINATOR_ID, "Originator"),
    "originator_headers_alt": build_user_headers(
        ORIGINATOR_ID_ALT, "Originator",
    ),
    # Opaque Servicer — shared constant is canonical.
    "servicer_headers": build_user_headers(SERVICER_ID, "Servicer"),
    "servicer_headers_alt": build_user_headers(
        SERVICER_ID_ALT, "Servicer",
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
# implementation will compare against in ownership checks (Heloc and
# Property both expose borrower_id; child collections roll up through
# Heloc.borrower_id). PRD §2.1, §3.10.
# ---------------------------------------------------------------------------
def make_borrower_headers(borrower_id: str) -> Dict[str, str]:
    """For Borrower (entity_backed:Borrower). Pass the actual
    Borrower.id of the acting borrower.

    PRD §2.1: "the value of X-User-ID is the id of the acting Borrower;
    any borrower-scoped read ... compares the resource's owning
    borrower chain to X-User-ID and rejects mismatches with
    ERR_FORBIDDEN."

    Every Borrower-driven call whose success depends on owning the
    targeted resource MUST use this builder, not the shared
    BORROWER_FALLBACK_ID constant.
    """
    return build_user_headers(borrower_id, "Borrower")


def make_originator_headers(originator_id: str) -> Dict[str, str]:
    """For Originator (opaque). Any non-empty operator id is fine."""
    return build_user_headers(originator_id, "Originator")


def make_servicer_headers(servicer_id: str) -> Dict[str, str]:
    """For Servicer (opaque). Distinct ids per call enable
    segregation-of-duties tests."""
    return build_user_headers(servicer_id, "Servicer")


def make_platform_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlatformAdmin (opaque)."""
    return build_user_headers(admin_id, "PlatformAdmin")


__all__ = [
    "ORIGINATOR_ID",
    "ORIGINATOR_ID_ALT",
    "SERVICER_ID",
    "SERVICER_ID_ALT",
    "PLATFORM_ADMIN_ID",
    "BORROWER_FALLBACK_ID",
    "TEST_USERS",
    "make_borrower_headers",
    "make_originator_headers",
    "make_servicer_headers",
    "make_platform_admin_headers",
]
