"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

OPAQUE roles — X-User-ID is an opaque operator identifier that is not
tied to any persisted entity row. Shared constants are canonical:
  - Examiner   (PRD §2.1: "X-User-ID is an opaque operator identifier
    not tied to any persisted entity ... does not compare it to any
    entity's id")
  - USPTOAdmin (same — opaque)

ENTITY-BACKED roles — PRD §2.1:
  - Applicant: "the value of X-User-ID is the id of the acting Applicant
    row in the database; every ownership check on an applicant-scoped
    resource ... compares the resource's owning applicant_id to
    X-User-ID, and a mismatch is also reported as ERR_FORBIDDEN."

Every Applicant call whose success depends on the resource belonging
to the right Applicant MUST mint headers via
make_applicant_headers(applicant_id) — never the shared fallback
constant. The shared APPLICANT_FALLBACK_ID below is reserved for tests
that do NOT exercise ownership (missing-header, role-mismatch,
NotFound, or RBAC-denied paths).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Opaque-role canonical ids — shared constants are PRD-correct because
# the server records but does not match these against any entity id
# (PRD §2.1).
# ---------------------------------------------------------------------------
EXAMINER_ID = "examiner-1"
EXAMINER_ID_ALT = "examiner-2"
USPTO_ADMIN_ID = "uspto-admin-1"
USPTO_ADMIN_ID_ALT = "uspto-admin-2"


# ---------------------------------------------------------------------------
# Entity-backed-role fallback id — DO NOT USE for ownership-gated calls.
# Use make_applicant_headers(applicant["id"]) with the actual id.
# ---------------------------------------------------------------------------
APPLICANT_FALLBACK_ID = "applicant-fallback"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants are canonical (PRD §2.1).
    "examiner_headers": build_user_headers(EXAMINER_ID, "Examiner"),
    "examiner_headers_alt": build_user_headers(EXAMINER_ID_ALT, "Examiner"),
    "uspto_admin_headers": build_user_headers(USPTO_ADMIN_ID, "USPTOAdmin"),
    "uspto_admin_headers_alt": build_user_headers(USPTO_ADMIN_ID_ALT, "USPTOAdmin"),

    # Entity-backed fallback — safe ONLY for non-ownership tests.
    "applicant_headers": build_user_headers(APPLICANT_FALLBACK_ID, "Applicant"),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Applicant role on
# ownership-gated calls. Pass the Applicant.id of the resource owner so
# PRD §2.1 ownership checks pass.
# ---------------------------------------------------------------------------
def make_applicant_headers(applicant_id: str) -> Dict[str, str]:
    """For Applicant (entity_backed:Applicant). Pass the Applicant.id of
    the applicant that owns the resource being operated on.

    PRD §2.1: "the value of X-User-ID is the id of the acting Applicant
    row in the database; every ownership check on an applicant-scoped
    resource (an Application, OfficeAction, MaintenanceFee, PCTPhase,
    FeeTransaction, or Response) compares the resource's owning
    applicant_id to X-User-ID, and a mismatch is also reported as
    ERR_FORBIDDEN."
    """
    return build_user_headers(applicant_id, "Applicant")


def make_examiner_headers(examiner_id: str) -> Dict[str, str]:
    """For Examiner (opaque). The id is recorded but not compared to
    any entity (PRD §2.1)."""
    return build_user_headers(examiner_id, "Examiner")


def make_uspto_admin_headers(admin_id: str) -> Dict[str, str]:
    """For USPTOAdmin (opaque). The id is recorded but not compared to
    any entity (PRD §2.1)."""
    return build_user_headers(admin_id, "USPTOAdmin")


__all__ = [
    "EXAMINER_ID",
    "EXAMINER_ID_ALT",
    "USPTO_ADMIN_ID",
    "USPTO_ADMIN_ID_ALT",
    "APPLICANT_FALLBACK_ID",
    "TEST_USERS",
    "make_applicant_headers",
    "make_examiner_headers",
    "make_uspto_admin_headers",
]
