"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Taxpayer is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Taxpayer,
  X-User-ID is the id of the acting Taxpayer entity. Ownership checks
  on any resource that references a Taxpayer (directly or transitively
  through its parent TaxReturn) compare the resource's taxpayer_id
  foreign-key field - or the taxpayer_id of the resource's owning
  return - to X-User-ID. A Taxpayer principal may only read and mutate
  resources whose ownership chain resolves to their own id."

  Every Taxpayer-acting call whose success depends on owning the
  targeted resource MUST mint headers via
  make_taxpayer_headers(taxpayer["id"]) -- never via the shared
  TAXPAYER_FALLBACK_ID constant. Falling back to the shared constant
  for an entity-backed role reproduces the canonical bug: the literal
  "fallback-taxpayer-1" never equals any real Taxpayer.id, so every
  ownership check rejects every request as ERR_FORBIDDEN regardless
  of implementation correctness.

- IRSAdjudicator is OPAQUE. PRD §2.1: "When X-User-Role is
  IRSAdjudicator, X-User-ID is an opaque operator identifier not tied
  to any persisted entity. The server may record it on the audit log
  ... but does not compare it to any entity's id." Shared constants
  are canonical.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
IRS_ADJUDICATOR_ID: str = "irs-adjudicator-001"
IRS_ADJUDICATOR_ID_ALT: str = "irs-adjudicator-002"

# Entity-backed fallback id — DO NOT use for ownership-gated Taxpayer
# calls. Safe only for header-missing / role-mismatch / NotFound paths.
TAXPAYER_FALLBACK_ID: str = "fallback-taxpayer-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque IRSAdjudicator — shared constant is canonical.
    "irs_adjudicator_headers": build_user_headers(
        IRS_ADJUDICATOR_ID, "IRSAdjudicator",
    ),
    "irs_adjudicator_headers_alt": build_user_headers(
        IRS_ADJUDICATOR_ID_ALT, "IRSAdjudicator",
    ),
    # Entity-backed Taxpayer fallback — DO NOT use for ownership-gated
    # calls. Safe only for header-missing / role-mismatch / 404 paths.
    "taxpayer_fallback_headers": build_user_headers(
        TAXPAYER_FALLBACK_ID, "Taxpayer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — REQUIRED for entity-backed Taxpayer.
# The runtime Taxpayer.id minted by POST /taxpayers is the value the
# implementation will compare against in ownership checks.
# ---------------------------------------------------------------------------
def make_taxpayer_headers(taxpayer_id: str) -> Dict[str, str]:
    """For Taxpayer (entity_backed:Taxpayer). Pass the actual
    Taxpayer.id of the acting taxpayer.

    PRD §2.1: "When X-User-Role is Taxpayer, X-User-ID is the id of
    the acting Taxpayer entity." Every Taxpayer-driven call whose
    success depends on owning the targeted TaxReturn / IncomeDocument
    / Schedule / TaxCredit / AmendedReturn / EstimatedTaxPayment MUST
    use this builder, not the shared TAXPAYER_FALLBACK_ID constant.
    """
    return build_user_headers(taxpayer_id, "Taxpayer")


def make_irs_adjudicator_headers(adjudicator_id: str) -> Dict[str, str]:
    """For IRSAdjudicator (opaque). Any non-empty operator id is fine;
    this builder exists so tests that want a distinct adjudicator id
    (e.g., for audit-token discrimination) can supply one without
    relying on a single shared constant.
    """
    return build_user_headers(adjudicator_id, "IRSAdjudicator")


__all__ = [
    "IRS_ADJUDICATOR_ID",
    "IRS_ADJUDICATOR_ID_ALT",
    "TAXPAYER_FALLBACK_ID",
    "TEST_USERS",
    "make_taxpayer_headers",
    "make_irs_adjudicator_headers",
]
