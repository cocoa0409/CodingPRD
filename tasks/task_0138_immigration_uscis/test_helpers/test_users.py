"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Officer / Supervisor are OPAQUE. PRD §2.1: "When X-User-Role is
  Officer, X-User-ID is an opaque operator identifier not tied to any
  persisted entity" and "When X-User-Role is Supervisor, X-User-ID is
  an opaque operator identifier not tied to any persisted entity,
  recorded only for audit." Shared constants are canonical.

- Petitioner is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  Petitioner, X-User-ID is the id of the acting Petitioner; ownership
  checks on any resource that references a Petitioner compare the
  resource's petitioner_id field to X-User-ID. Petitioners may read
  and act only on cases whose petitioner_id matches their own
  X-User-ID."

  Every Petitioner-acting call whose success depends on owning the
  targeted resource MUST mint headers via
  make_petitioner_headers(petitioner["id"]) — never via the shared
  PETITIONER_FALLBACK_ID constant. Falling back to the shared
  constant for an entity-backed role reproduces the canonical bug:
  the literal "fallback-petitioner-1" never equals any real
  Petitioner.id, so every ownership check rejects every request as
  ERR_FORBIDDEN regardless of implementation correctness.

- Beneficiary is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  Beneficiary, X-User-ID is the id of the acting Beneficiary;
  ownership checks compare the targeted case's beneficiary_id (or the
  targeted beneficiary record's own id) to X-User-ID."

  Use make_beneficiary_headers(beneficiary["id"]) for any
  ownership-gated call.

The shared *_FALLBACK_ID constants are ONLY safe for tests that DO
NOT exercise ownership (header-missing, role-mismatch on a
non-existent resource, or 404 paths).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
OFFICER_ID: str = "officer-001"
OFFICER_ID_ALT: str = "officer-002"

SUPERVISOR_ID: str = "supervisor-001"
SUPERVISOR_ID_ALT: str = "supervisor-002"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
# Safe only for header-missing / role-mismatch / NotFound paths.
PETITIONER_FALLBACK_ID: str = "fallback-petitioner-1"
BENEFICIARY_FALLBACK_ID: str = "fallback-beneficiary-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque Officer — shared constant is canonical.
    "officer_headers": build_user_headers(OFFICER_ID, "Officer"),
    "officer_headers_alt": build_user_headers(
        OFFICER_ID_ALT, "Officer",
    ),
    # Opaque Supervisor — shared constant is canonical.
    "supervisor_headers": build_user_headers(SUPERVISOR_ID, "Supervisor"),
    "supervisor_headers_alt": build_user_headers(
        SUPERVISOR_ID_ALT, "Supervisor",
    ),
    # Entity-backed Petitioner fallback — DO NOT use for ownership-
    # gated calls. Safe only for header-missing / role-mismatch / 404
    # paths.
    "petitioner_fallback_headers": build_user_headers(
        PETITIONER_FALLBACK_ID, "Petitioner",
    ),
    # Entity-backed Beneficiary fallback — same caveat.
    "beneficiary_fallback_headers": build_user_headers(
        BENEFICIARY_FALLBACK_ID, "Beneficiary",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Petitioner and
# Beneficiary. The runtime Petitioner.id / Beneficiary.id minted by
# their respective POST endpoints is the value the implementation will
# compare against in ownership checks.
# ---------------------------------------------------------------------------
def make_petitioner_headers(petitioner_id: str) -> Dict[str, str]:
    """For Petitioner (entity_backed:Petitioner). Pass the actual
    Petitioner.id of the acting sponsor.

    PRD §2.1: "When X-User-Role is Petitioner, X-User-ID is the id of
    the acting Petitioner; ownership checks on any resource that
    references a Petitioner compare the resource's petitioner_id field
    to X-User-ID. Petitioners may read and act only on cases whose
    petitioner_id matches their own X-User-ID."

    Every Petitioner-driven call whose success depends on owning the
    targeted Petitioner / Beneficiary / Case MUST use this builder, not
    the shared PETITIONER_FALLBACK_ID constant.
    """
    return build_user_headers(petitioner_id, "Petitioner")


def make_beneficiary_headers(beneficiary_id: str) -> Dict[str, str]:
    """For Beneficiary (entity_backed:Beneficiary). Pass the actual
    Beneficiary.id of the acting beneficiary.

    PRD §2.1: "When X-User-Role is Beneficiary, X-User-ID is the id of
    the acting Beneficiary; ownership checks compare the targeted
    case's beneficiary_id (or the targeted beneficiary record's own
    id) to X-User-ID."
    """
    return build_user_headers(beneficiary_id, "Beneficiary")


def make_officer_headers(officer_id: str) -> Dict[str, str]:
    """For Officer (opaque). Any non-empty operator id is fine; this
    builder exists so tests that want a distinct officer id (e.g., for
    audit-token discrimination) can supply one without relying on a
    single shared constant.
    """
    return build_user_headers(officer_id, "Officer")


def make_supervisor_headers(supervisor_id: str) -> Dict[str, str]:
    """For Supervisor (opaque)."""
    return build_user_headers(supervisor_id, "Supervisor")


__all__ = [
    "OFFICER_ID",
    "OFFICER_ID_ALT",
    "SUPERVISOR_ID",
    "SUPERVISOR_ID_ALT",
    "PETITIONER_FALLBACK_ID",
    "BENEFICIARY_FALLBACK_ID",
    "TEST_USERS",
    "make_petitioner_headers",
    "make_beneficiary_headers",
    "make_officer_headers",
    "make_supervisor_headers",
]
