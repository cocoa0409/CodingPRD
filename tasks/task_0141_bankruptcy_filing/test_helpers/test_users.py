"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Trustee and Judge are OPAQUE. PRD §2.1: "When X-User-Role is Trustee,
  the X-User-ID value is an opaque court-appointed-administrator
  identifier not tied to any persisted entity — the server may record it
  for audit but does not compare it to any entity's id; trustees act on
  cases at large rather than on entities they own. When X-User-Role is
  Judge, the X-User-ID value is likewise an opaque court-officer
  identifier not tied to any persisted entity, used for the two judicial
  actions of plan confirmation and discharge."
  Shared constants are canonical for these operator-only roles.

- Debtor is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Debtor, the
  X-User-ID value is the id of the acting Debtor; ownership checks on
  any case-scoped resource compare Case.debtor_id to X-User-ID, so
  debtors may only act on their own cases, schedules, plans, and
  case-scoped resources."

- Creditor is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Creditor,
  the X-User-ID value is the id of the acting Creditor; ownership
  checks compare Claim.creditor_id and CollectionAction.creditor_id to
  X-User-ID, so creditors may only file claims and attempt collection
  actions in their own name."

Every Debtor- or Creditor-acting call whose success depends on owning
the targeted resource MUST mint headers via make_debtor_headers(
debtor["id"]) or make_creditor_headers(creditor["id"]). Falling back to
the shared fallback constant for entity-backed roles reproduces the
canonical bug: the literal "fallback-debtor-1" never equals any real
Debtor.id, so every ownership check rejects every request as
ERR_FORBIDDEN.

The shared *_FALLBACK_ID constants are ONLY safe for tests that DO NOT
exercise ownership (header-missing, role-mismatch, 404 on
non-existent path).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
TRUSTEE_ID = "trustee-001"
TRUSTEE_ID_ALT = "trustee-002"
JUDGE_ID = "judge-001"
JUDGE_ID_ALT = "judge-002"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
DEBTOR_FALLBACK_ID = "fallback-debtor-1"
CREDITOR_FALLBACK_ID = "fallback-creditor-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque Trustee — shared constant is canonical.
    "trustee_headers": build_user_headers(TRUSTEE_ID, "Trustee"),
    "trustee_headers_alt": build_user_headers(
        TRUSTEE_ID_ALT, "Trustee",
    ),
    # Opaque Judge — shared constant is canonical.
    "judge_headers": build_user_headers(JUDGE_ID, "Judge"),
    "judge_headers_alt": build_user_headers(
        JUDGE_ID_ALT, "Judge",
    ),
    # Entity-backed Debtor fallback — DO NOT use for ownership-gated
    # calls. Safe only for header-missing / role-mismatch / NotFound paths.
    "debtor_fallback_headers": build_user_headers(
        DEBTOR_FALLBACK_ID, "Debtor",
    ),
    # Entity-backed Creditor fallback — DO NOT use for ownership-gated
    # calls. Safe only for header-missing / role-mismatch / NotFound paths.
    "creditor_fallback_headers": build_user_headers(
        CREDITOR_FALLBACK_ID, "Creditor",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Debtor and Creditor.
# The runtime Debtor.id / Creditor.id minted by POST /debtors and POST
# /creditors are the values the implementation will compare against in
# ownership checks.
# ---------------------------------------------------------------------------
def make_debtor_headers(debtor_id: str) -> Dict[str, str]:
    """For Debtor (entity_backed:Debtor). Pass the actual Debtor.id of
    the acting debtor.

    PRD §2.1: "When X-User-Role is Debtor, the X-User-ID value is the
    id of the acting Debtor; ownership checks on any case-scoped
    resource compare Case.debtor_id to X-User-ID, so debtors may only
    act on their own cases, schedules, plans, and case-scoped
    resources."

    Every Debtor-acting call whose success depends on owning the
    targeted resource (POST /cases, POST /cases/{id}/schedules,
    POST /cases/{id}/file, DELETE /cases/{id}, POST
    /cases/{id}/plans, DELETE /cases/{id}/plans/{plan_id}, POST
    /cases/{id}/plans/{plan_id}/payments, POST /cases/{id}/means-test)
    MUST use this builder.
    """
    return build_user_headers(debtor_id, "Debtor")


def make_creditor_headers(creditor_id: str) -> Dict[str, str]:
    """For Creditor (entity_backed:Creditor). Pass the actual
    Creditor.id of the acting creditor.

    PRD §2.1: "When X-User-Role is Creditor, the X-User-ID value is
    the id of the acting Creditor; ownership checks compare
    Claim.creditor_id and CollectionAction.creditor_id to X-User-ID."

    Every Creditor-acting write whose success depends on owning the
    targeted claim or collection-action (POST /cases/{id}/claims,
    POST /collection-actions) MUST use this builder.
    """
    return build_user_headers(creditor_id, "Creditor")


def make_trustee_headers(trustee_id: str) -> Dict[str, str]:
    """For Trustee (opaque). Any non-empty operator id is fine; this
    builder exists so tests that want a distinct trustee id can supply
    one without relying on a single shared constant.
    """
    return build_user_headers(trustee_id, "Trustee")


def make_judge_headers(judge_id: str) -> Dict[str, str]:
    """For Judge (opaque)."""
    return build_user_headers(judge_id, "Judge")


__all__ = [
    "TRUSTEE_ID",
    "TRUSTEE_ID_ALT",
    "JUDGE_ID",
    "JUDGE_ID_ALT",
    "DEBTOR_FALLBACK_ID",
    "CREDITOR_FALLBACK_ID",
    "TEST_USERS",
    "make_debtor_headers",
    "make_creditor_headers",
    "make_trustee_headers",
    "make_judge_headers",
]
