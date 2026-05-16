"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PlanAdmin / BenefitsCounselor / Auditor are OPAQUE. PRD §2.1: "When
  X-User-Role is PlanAdmin, BenefitsCounselor, or Auditor, X-User-ID is
  an opaque operator identifier not tied to any persisted entity; the
  server may compare two X-User-ID values for equality (this is how
  segregation-of-duties on adjudication is enforced) but never compares
  it to any entity's id." Shared constants are canonical for these
  operator-only roles.

- Beneficiary is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  Beneficiary, X-User-ID is the id of the acting Beneficiary;
  ownership checks on any resource that references a Beneficiary
  compare the resource's beneficiary_id to X-User-ID, and any read of a
  resource whose beneficiary_id differs from X-User-ID is rejected with
  ERR_FORBIDDEN."

  Every Beneficiary-acting read whose success depends on owning the
  targeted resource MUST mint headers via
  make_beneficiary_headers(beneficiary["id"]) — never via the shared
  BENEFICIARY_FALLBACK_ID constant. Falling back to the shared constant
  for entity-backed roles reproduces the canonical bug: the literal
  "fallback-beneficiary-1" never equals any real Beneficiary.id, so
  every ownership check rejects every request as ERR_FORBIDDEN.

The shared BENEFICIARY_FALLBACK_ID constant is ONLY safe for tests
that DO NOT exercise ownership (header-missing, role-mismatch, 404
on non-existent path).

Segregation-of-duties: counselor submission and admin adjudication of a
DrugClaim need DIFFERENT operator X-User-ID values. Use the two distinct
admin/counselor constants below to ensure adjudication is performed by
a different operator than the submitting counselor (PRD §3.8:
"if X-User-ID of the adjudication call equals the X-User-ID recorded
at submission, the request is rejected with ERR_SEGREGATION_OF_DUTIES").
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PLAN_ADMIN_ID = "admin-001"
PLAN_ADMIN_ID_ALT = "admin-002"

COUNSELOR_ID = "counselor-001"
COUNSELOR_ID_ALT = "counselor-002"

AUDITOR_ID = "auditor-001"

# Entity-backed fallback id — DO NOT use for ownership-gated calls.
BENEFICIARY_FALLBACK_ID = "fallback-beneficiary-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque PlanAdmin — shared constant is canonical.
    "admin_headers": build_user_headers(PLAN_ADMIN_ID, "PlanAdmin"),
    "admin_headers_alt": build_user_headers(
        PLAN_ADMIN_ID_ALT, "PlanAdmin",
    ),
    # Opaque BenefitsCounselor — shared constant is canonical.
    "counselor_headers": build_user_headers(
        COUNSELOR_ID, "BenefitsCounselor",
    ),
    "counselor_headers_alt": build_user_headers(
        COUNSELOR_ID_ALT, "BenefitsCounselor",
    ),
    # Opaque Auditor — shared constant is canonical.
    "auditor_headers": build_user_headers(AUDITOR_ID, "Auditor"),
    # Entity-backed Beneficiary fallback — DO NOT use for
    # ownership-gated calls. Safe only for header-missing / role-
    # mismatch / NotFound paths.
    "beneficiary_fallback_headers": build_user_headers(
        BENEFICIARY_FALLBACK_ID, "Beneficiary",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Beneficiary.
# The runtime Beneficiary.id minted by POST /beneficiaries is the value
# the implementation will compare against in ownership checks.
# ---------------------------------------------------------------------------
def make_beneficiary_headers(beneficiary_id: str) -> Dict[str, str]:
    """For Beneficiary (entity_backed:Beneficiary). Pass the actual
    Beneficiary.id of the acting beneficiary.

    PRD §2.1: "When X-User-Role is Beneficiary, X-User-ID is the id of
    the acting Beneficiary; ownership checks on any resource that
    references a Beneficiary compare the resource's beneficiary_id to
    X-User-ID, and any read of a resource whose beneficiary_id differs
    from X-User-ID is rejected with ERR_FORBIDDEN."

    Every Beneficiary-driven read whose success depends on owning the
    targeted Enrollment / DrugClaim / MedigapPolicy / DrugPhaseLedger
    (e.g., GET /beneficiaries/{id}, GET
    /beneficiaries/{beneficiary_id}/enrollments, GET
    /beneficiaries/{beneficiary_id}/drug-phase-ledger, GET
    /beneficiaries/{beneficiary_id}/drug-cost-estimate, GET
    /enrollments/{id}/cost-summary on an owned enrollment) MUST use this
    builder, not the shared BENEFICIARY_FALLBACK_ID constant.
    """
    return build_user_headers(beneficiary_id, "Beneficiary")


def make_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlanAdmin (opaque). Any non-empty operator id is fine; this
    builder exists so tests that want a distinct admin id (for
    audit-token discrimination in segregation-of-duties scenarios) can
    supply one without relying on a single shared constant.
    """
    return build_user_headers(admin_id, "PlanAdmin")


def make_counselor_headers(counselor_id: str) -> Dict[str, str]:
    """For BenefitsCounselor (opaque). PRD §3.8: "The admin who performs
    adjudication cannot be the same operator who submitted the claim".
    Two distinct counselor ids let tests model two different counselors
    when needed.
    """
    return build_user_headers(counselor_id, "BenefitsCounselor")


def make_auditor_headers(auditor_id: str) -> Dict[str, str]:
    """For Auditor (opaque)."""
    return build_user_headers(auditor_id, "Auditor")


__all__ = [
    "PLAN_ADMIN_ID",
    "PLAN_ADMIN_ID_ALT",
    "COUNSELOR_ID",
    "COUNSELOR_ID_ALT",
    "AUDITOR_ID",
    "BENEFICIARY_FALLBACK_ID",
    "TEST_USERS",
    "make_beneficiary_headers",
    "make_admin_headers",
    "make_counselor_headers",
    "make_auditor_headers",
]
