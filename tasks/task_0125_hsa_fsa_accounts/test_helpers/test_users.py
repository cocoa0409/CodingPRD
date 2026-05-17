"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PlanAdministrator / ClaimAdjudicator / Auditor are OPAQUE. PRD §2.1:
  "When X-User-Role is PlanAdministrator, X-User-ID is an opaque
  operator identifier not tied to any persisted entity. The server
  records it as actor_user_id on every AuditEvent it produces, but
  does not compare it to any entity's id. The same convention applies
  to ClaimAdjudicator ... Auditor is likewise an opaque, identity-less
  read-only operator". Shared constants are canonical for these roles.

- AccountHolder is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  AccountHolder, X-User-ID is the id of the acting AccountHolder
  entity. Ownership checks compare the account_holder_id on an Account
  (and transitively, the account_id on resources nested under it) to
  X-User-ID; access to any resource whose owning AccountHolder.id does
  not equal X-User-ID is rejected with ERR_NOT_FOUND".

  Every AccountHolder-acting call whose success depends on owning the
  targeted resource MUST mint headers via
  make_account_holder_headers(account_holder["id"]) — never via the
  shared ACCOUNT_HOLDER_FALLBACK_ID constant. Falling back to the
  shared constant for entity-backed roles reproduces the canonical
  bug: the literal "fallback-account-holder-1" never equals any real
  AccountHolder.id, so every ownership check rejects every request as
  ERR_NOT_FOUND.

The shared ACCOUNT_HOLDER_FALLBACK_ID constant is ONLY safe for tests
that DO NOT exercise ownership (header-missing, role-mismatch,
404-on-non-existent-path, or RBAC role-not-permitted assertions).

SEGREGATION OF DUTIES — PRD §2.9: "Approval and denial of a SUBMITTED
claim ... the actor_user_id recorded on the CLAIM_SUBMITTED event for
a given claim is compared to the current X-User-ID whenever that claim
is approved or denied; if they match, the operation is rejected with
ERR_SEGREGATION_OF_DUTIES". Two distinct ClaimAdjudicator ids let
tests model a clean (non-equal) adjudicator for normal approvals and a
deliberately equal id for ERR_SEGREGATION_OF_DUTIES assertions.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PLAN_ADMIN_ID = "plan-admin-001"
PLAN_ADMIN_ID_ALT = "plan-admin-002"

CLAIM_ADJUDICATOR_ID = "adjudicator-001"
CLAIM_ADJUDICATOR_ID_ALT = "adjudicator-002"

AUDITOR_ID = "auditor-001"

# Entity-backed fallback id — DO NOT use for ownership-gated calls.
ACCOUNT_HOLDER_FALLBACK_ID = "fallback-account-holder-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque PlanAdministrator — shared constant is canonical.
    "plan_admin_headers": build_user_headers(
        PLAN_ADMIN_ID, "PlanAdministrator",
    ),
    "plan_admin_headers_alt": build_user_headers(
        PLAN_ADMIN_ID_ALT, "PlanAdministrator",
    ),
    # Opaque ClaimAdjudicator — shared constant is canonical for
    # non-SoD adjudication calls.
    "adjudicator_headers": build_user_headers(
        CLAIM_ADJUDICATOR_ID, "ClaimAdjudicator",
    ),
    "adjudicator_headers_alt": build_user_headers(
        CLAIM_ADJUDICATOR_ID_ALT, "ClaimAdjudicator",
    ),
    # Opaque Auditor — shared constant is canonical.
    "auditor_headers": build_user_headers(AUDITOR_ID, "Auditor"),
    # Entity-backed AccountHolder fallback — DO NOT use for
    # ownership-gated calls.
    "account_holder_fallback_headers": build_user_headers(
        ACCOUNT_HOLDER_FALLBACK_ID, "AccountHolder",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed AccountHolder.
# The runtime AccountHolder.id minted by POST /account-holders is the
# value the implementation will compare against in ownership checks.
# ---------------------------------------------------------------------------
def make_account_holder_headers(account_holder_id: str) -> Dict[str, str]:
    """For AccountHolder (entity_backed:AccountHolder). Pass the actual
    AccountHolder.id of the acting holder.

    PRD §2.1: "When X-User-Role is AccountHolder, X-User-ID is the id
    of the acting AccountHolder entity. Ownership checks compare the
    account_holder_id on an Account ... to X-User-ID".

    Every AccountHolder-driven call whose success depends on owning
    the targeted resource MUST use this builder, not the shared
    ACCOUNT_HOLDER_FALLBACK_ID constant.
    """
    return build_user_headers(account_holder_id, "AccountHolder")


def make_plan_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlanAdministrator (opaque). Any non-empty operator id is
    fine; this builder exists so tests that want a distinct admin id
    can supply one without relying on a single shared constant.
    """
    return build_user_headers(admin_id, "PlanAdministrator")


def make_adjudicator_headers(adjudicator_id: str) -> Dict[str, str]:
    """For ClaimAdjudicator (opaque). PRD §2.1: "Different adjudicator
    X-User-ID values are nevertheless meaningful — they are how the
    segregation-of-duties rule distinguishes the person who submitted
    from the person who approves or denies." Tests that need to model
    an explicit SoD violation (X-User-ID equal to the submitting
    AccountHolder.id) construct headers via this builder.
    """
    return build_user_headers(adjudicator_id, "ClaimAdjudicator")


def make_auditor_headers(auditor_id: str) -> Dict[str, str]:
    """For Auditor (opaque)."""
    return build_user_headers(auditor_id, "Auditor")


__all__ = [
    "PLAN_ADMIN_ID",
    "PLAN_ADMIN_ID_ALT",
    "CLAIM_ADJUDICATOR_ID",
    "CLAIM_ADJUDICATOR_ID_ALT",
    "AUDITOR_ID",
    "ACCOUNT_HOLDER_FALLBACK_ID",
    "TEST_USERS",
    "make_account_holder_headers",
    "make_plan_admin_headers",
    "make_adjudicator_headers",
    "make_auditor_headers",
]
