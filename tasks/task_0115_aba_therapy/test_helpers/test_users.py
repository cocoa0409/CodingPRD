"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- BCBA and RBT are ENTITY-BACKED. PRD §2.1: "When X-User-Role is BCBA,
  X-User-ID is the id of the acting Therapist row whose credential
  equals BCBA; ownership checks on any resource that references a
  Therapist (for example, an evaluation's evaluator_therapist_id or a
  session's therapist_id) compare the resource's foreign-key field to
  X-User-ID." PRD §2.1 (RBT clause): "When X-User-Role is RBT,
  X-User-ID is the id of the acting Therapist row whose credential
  equals RBT; the same ownership rule applies — a session's
  therapist_id is compared against X-User-ID whenever the RBT acts on
  it."

  Every BCBA- or RBT-driven call whose success depends on owning the
  targeted DiagnosticEvaluation / TherapySession MUST mint headers via
  make_bcba_headers(therapist["id"]) or make_rbt_headers(therapist["id"])
  — never via the shared *_FALLBACK_ID constant. Falling back to the
  shared constant for entity-backed roles reproduces the canonical bug:
  the literal "fallback-bcba-1" never equals any real Therapist.id, so
  every ownership check rejects every request, cascading "Setup failed"
  into dozens of tests downstream.

- ClinicAdmin and PayerAdmin are OPAQUE. PRD §2.1 (ClinicAdmin clause):
  "When X-User-Role is ClinicAdmin, X-User-ID is an opaque operator
  identifier not tied to any persisted entity. The server may record it
  for audit but never compares it to any entity's id." PRD §2.1
  (PayerAdmin clause): "When X-User-Role is PayerAdmin, X-User-ID is
  likewise an opaque operator identifier not tied to any persisted
  entity and is never compared to any entity's id."
  Shared constants in TEST_USERS are canonical for these two roles.

The shared *_FALLBACK_ID constants are ONLY safe for tests that DO NOT
exercise ownership (auth-missing, role-mismatch, NotFound on unrelated
paths). Ownership-gated calls MUST use the per-instance builder.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
CLINIC_ADMIN_ID = "clinic-admin-001"
CLINIC_ADMIN_ID_ALT = "clinic-admin-002"

PAYER_ADMIN_ID = "payer-admin-001"
PAYER_ADMIN_ID_ALT = "payer-admin-002"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
BCBA_FALLBACK_ID = "fallback-bcba-1"
RBT_FALLBACK_ID = "fallback-rbt-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # ClinicAdmin — opaque
    "clinic_admin_headers": build_user_headers(
        CLINIC_ADMIN_ID, "ClinicAdmin",
    ),
    "clinic_admin_headers_alt": build_user_headers(
        CLINIC_ADMIN_ID_ALT, "ClinicAdmin",
    ),
    # PayerAdmin — opaque
    "payer_admin_headers": build_user_headers(
        PAYER_ADMIN_ID, "PayerAdmin",
    ),
    "payer_admin_headers_alt": build_user_headers(
        PAYER_ADMIN_ID_ALT, "PayerAdmin",
    ),
    # BCBA — entity-backed FALLBACK. Safe only for auth/role/NotFound
    # paths; ownership-gated calls MUST use make_bcba_headers.
    "bcba_fallback_headers": build_user_headers(
        BCBA_FALLBACK_ID, "BCBA",
    ),
    # RBT — entity-backed FALLBACK. Safe only for auth/role/NotFound
    # paths; ownership-gated calls MUST use make_rbt_headers.
    "rbt_fallback_headers": build_user_headers(
        RBT_FALLBACK_ID, "RBT",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed BCBA and RBT.
# ---------------------------------------------------------------------------
def make_bcba_headers(therapist_id: str) -> Dict[str, str]:
    """For BCBA (entity_backed:Therapist with credential=BCBA). Pass the
    actual Therapist.id of the acting BCBA.

    PRD §2.1: "When X-User-Role is BCBA, X-User-ID is the id of the
    acting Therapist row whose credential equals BCBA; ownership checks
    on any resource that references a Therapist (for example, an
    evaluation's evaluator_therapist_id or a session's therapist_id)
    compare the resource's foreign-key field to X-User-ID."

    Every BCBA-driven call whose success depends on owning the targeted
    evaluation or session (start/complete/dispute/resolve-dispute) MUST
    use this builder, not the shared BCBA_FALLBACK_ID constant.
    """
    return build_user_headers(therapist_id, "BCBA")


def make_rbt_headers(therapist_id: str) -> Dict[str, str]:
    """For RBT (entity_backed:Therapist with credential=RBT). Pass the
    actual Therapist.id of the acting RBT.

    PRD §2.1: "When X-User-Role is RBT, X-User-ID is the id of the
    acting Therapist row whose credential equals RBT; the same
    ownership rule applies — a session's therapist_id is compared
    against X-User-ID whenever the RBT acts on it."
    """
    return build_user_headers(therapist_id, "RBT")


def make_clinic_admin_headers(user_id: str) -> Dict[str, str]:
    """For ClinicAdmin (opaque). Any non-empty operator id is fine."""
    return build_user_headers(user_id, "ClinicAdmin")


def make_payer_admin_headers(user_id: str) -> Dict[str, str]:
    """For PayerAdmin (opaque). Any non-empty operator id is fine."""
    return build_user_headers(user_id, "PayerAdmin")


__all__ = [
    "CLINIC_ADMIN_ID",
    "CLINIC_ADMIN_ID_ALT",
    "PAYER_ADMIN_ID",
    "PAYER_ADMIN_ID_ALT",
    "BCBA_FALLBACK_ID",
    "RBT_FALLBACK_ID",
    "TEST_USERS",
    "make_bcba_headers",
    "make_rbt_headers",
    "make_clinic_admin_headers",
    "make_payer_admin_headers",
]
