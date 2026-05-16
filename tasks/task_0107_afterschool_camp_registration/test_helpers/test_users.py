"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- ProgramAdmin is OPAQUE. PRD §2.1: "When X-User-Role is ProgramAdmin,
  X-User-ID is an opaque operator identifier not tied to any persisted
  entity; the server treats it as an audit token and does not compare
  it to any entity's id." The shared admin_headers constant is canonical
  for this operator-only role.

- Guardian is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Guardian,
  X-User-ID is the id of the acting Guardian row; ownership checks on
  any resource that references a Guardian (and, by extension, the
  Family to which that Guardian belongs) compare the resource's family
  lineage to the family of the Guardian whose id matches X-User-ID."

  Every Guardian call whose success depends on owning the targeted
  Child / Enrollment / EmergencyContact / Authorization MUST mint
  headers via make_guardian_headers(guardian["id"]) — never via the
  GUARDIAN_FALLBACK_ID shared constant. Falling back to the shared
  constant for entity-backed roles reproduces the canonical bug: the
  literal "fallback-guardian-1" never equals any real Guardian.id, so
  every ownership check rejects every request as ERR_FAMILY_MISMATCH.

The shared GUARDIAN_FALLBACK_ID constant is ONLY safe for tests that
DO NOT exercise ownership (header-missing, role-mismatch, NotFound on
unrelated paths). Ownership-gated calls MUST use the per-instance
builder.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PROGRAM_ADMIN_ID = "admin-001"
PROGRAM_ADMIN_ID_ALT = "admin-002"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
GUARDIAN_FALLBACK_ID = "fallback-guardian-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque ProgramAdmin — shared constant is canonical.
    "admin_headers": build_user_headers(PROGRAM_ADMIN_ID, "ProgramAdmin"),
    "admin_headers_alt": build_user_headers(
        PROGRAM_ADMIN_ID_ALT, "ProgramAdmin",
    ),
    # Entity-backed Guardian fallback — DO NOT use for ownership-gated
    # calls. Safe only for auth/role-rejection / NotFound paths.
    "guardian_fallback_headers": build_user_headers(
        GUARDIAN_FALLBACK_ID, "Guardian",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Guardian.
# The runtime Guardian.id minted by POST /camp/families/{id}/guardians is
# the value the implementation will compare against in ownership checks.
# ---------------------------------------------------------------------------
def make_guardian_headers(guardian_id: str) -> Dict[str, str]:
    """For Guardian (entity_backed:Guardian). Pass the actual Guardian.id
    of the acting guardian.

    PRD §2.1: "X-User-ID is the id of the acting Guardian row;
    ownership checks on any resource that references a Guardian (and,
    by extension, the Family to which that Guardian belongs) compare
    the resource's family lineage to the family of the Guardian whose
    id matches X-User-ID."

    Every Guardian-driven call whose success depends on owning the
    targeted Child / Enrollment / EmergencyContact / Authorization
    (e.g., POST /camp/families/{family_id}/children, POST
    /camp/children/{child_id}/emergency-contacts, POST
    /camp/children/{child_id}/authorizations, POST /camp/enrollments,
    POST /camp/enrollments/{id}/confirm, POST
    /camp/enrollments/{id}/cancel, POST
    /camp/authorizations/{id}/revoke, GET /camp/families/{id}, GET
    /camp/families/{id}/invoice) MUST use this builder, not the shared
    GUARDIAN_FALLBACK_ID constant.
    """
    return build_user_headers(guardian_id, "Guardian")


def make_admin_headers(admin_id: str) -> Dict[str, str]:
    """For ProgramAdmin (opaque). Any non-empty operator id is fine;
    this builder exists so tests that want a distinct admin id (for
    audit-token discrimination in concurrency races) can supply one
    without relying on a single shared constant.
    """
    return build_user_headers(admin_id, "ProgramAdmin")


__all__ = [
    "PROGRAM_ADMIN_ID",
    "PROGRAM_ADMIN_ID_ALT",
    "GUARDIAN_FALLBACK_ID",
    "TEST_USERS",
    "make_guardian_headers",
    "make_admin_headers",
]
