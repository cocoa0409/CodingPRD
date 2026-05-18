"""Pre-built role headers for the two roles in PRD §2.1.

PRD §2.1 identity rules:

- PlatformAdmin is OPAQUE. PRD §2.1: "When X-User-Role is PlatformAdmin,
  X-User-ID is an opaque operator identifier not tied to any persisted
  entity. The server may record it for audit but does not compare it to
  any entity's id; a PlatformAdmin therefore acts across all accounts
  without ownership constraints." Shared constants are canonical for the
  operator role.

- Cardholder is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  Cardholder, X-User-ID is the id of the acting Cardholder entity;
  ownership checks on any resource that references a Cardholder compare
  the resource's cardholder_id foreign key (resolved either directly, as
  on an Account, or transitively through the account_id chain for
  Transaction, PointsTransfer, StatementCredit, QuarterlyActivation, and
  PointsLedgerEntry) to X-User-ID."

  Every Cardholder-acting call whose success depends on owning the
  targeted resource MUST mint headers via
  make_cardholder_headers(cardholder["id"]) — never via the shared
  CARDHOLDER_FALLBACK_ID constant. Falling back to the shared constant
  for entity-backed roles reproduces the canonical bug: the literal
  "fallback-cardholder-1" never equals any real Cardholder.id, so every
  ownership check rejects every request as ERR_FORBIDDEN.

  PRD §2.1: "A Cardholder attempting to operate on another cardholder's
  account ... is rejected with ERR_FORBIDDEN."

The shared CARDHOLDER_FALLBACK_ID constant is ONLY safe for tests that
DO NOT exercise ownership (header-missing, role-mismatch, 404-on-bogus
path).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_ID = "admin-001"
PLATFORM_ADMIN_ID_ALT = "admin-002"

# Entity-backed fallback id — DO NOT use for ownership-gated calls.
CARDHOLDER_FALLBACK_ID = "fallback-cardholder-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque PlatformAdmin — shared constant is canonical.
    "admin_headers": build_user_headers(
        PLATFORM_ADMIN_ID, "PlatformAdmin",
    ),
    "admin_headers_alt": build_user_headers(
        PLATFORM_ADMIN_ID_ALT, "PlatformAdmin",
    ),
    # Entity-backed Cardholder fallback — DO NOT use for ownership-gated
    # calls. Safe only for header-missing / role-mismatch / NotFound
    # paths.
    "cardholder_fallback_headers": build_user_headers(
        CARDHOLDER_FALLBACK_ID, "Cardholder",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Cardholder.
# The runtime Cardholder.id minted by POST /cardholders is the value the
# implementation will compare against in ownership checks.
# ---------------------------------------------------------------------------
def make_cardholder_headers(cardholder_id: str) -> Dict[str, str]:
    """For Cardholder (entity_backed:Cardholder). Pass the actual
    Cardholder.id of the acting cardholder.

    PRD §2.1: "When X-User-Role is Cardholder, X-User-ID is the id of the
    acting Cardholder entity; ownership checks on any resource that
    references a Cardholder compare the resource's cardholder_id foreign
    key (resolved either directly, as on an Account, or transitively
    through the account_id chain for Transaction, PointsTransfer,
    StatementCredit, QuarterlyActivation, and PointsLedgerEntry) to
    X-User-ID."

    Every Cardholder-driven call whose success depends on owning the
    targeted Account / Transaction / PointsTransfer / StatementCredit /
    QuarterlyActivation / PointsLedgerEntry (e.g., POST /transactions,
    POST /points-transfers, POST /statement-credits, POST
    /accounts/{id}/activate-category, POST /accounts/{id}/close, GET
    /accounts/{id}, GET /accounts/{id}/ledger, GET
    /accounts/{id}/activations, GET /accounts/{id}/transactions, POST
    /points-transfers/{id}/reverse) MUST use this builder, not the
    shared CARDHOLDER_FALLBACK_ID constant.
    """
    return build_user_headers(cardholder_id, "Cardholder")


def make_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlatformAdmin (opaque). Any non-empty operator id works; this
    builder exists so a test that wants a distinct admin id for audit-
    discrimination scenarios can supply one without relying on the
    single shared constant.
    """
    return build_user_headers(admin_id, "PlatformAdmin")


__all__ = [
    "PLATFORM_ADMIN_ID",
    "PLATFORM_ADMIN_ID_ALT",
    "CARDHOLDER_FALLBACK_ID",
    "TEST_USERS",
    "make_cardholder_headers",
    "make_admin_headers",
]
