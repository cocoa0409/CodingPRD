"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Judge, Mediator, PlatformAdmin are OPAQUE. PRD §2.1:
    - "When X-User-Role is Judge, X-User-ID is an opaque judicial-officer
      identifier not tied to any persisted entity."
    - "When X-User-Role is Mediator, X-User-ID is an opaque mediator
      identifier not tied to any persisted entity".
    - "When X-User-Role is PlatformAdmin, X-User-ID is an opaque
      operator identifier not tied to any persisted entity".
  Shared constants are canonical for these roles.

- Petitioner is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  Petitioner, X-User-ID is the id of the acting Party row (specifically,
  the Party on the targeted case whose role is PETITIONER). Ownership
  checks on any resource that references a Party (for example, the
  proposing_party_id of a ParentingPlan, or the party_id of a
  FinancialDisclosure) compare the resource's party foreign-key field
  to X-User-ID."

  Every Petitioner-acting call whose success depends on owning the
  targeted Party / Case / Disclosure / ParentingPlan MUST mint headers
  via make_petitioner_headers(party["id"]) using the actual Party.id
  returned by POST /cases. Falling back to the shared
  PETITIONER_FALLBACK_ID constant for an entity-backed role reproduces
  the canonical bug: the literal "fallback-petitioner-1" never equals
  any real Party.id, so every ownership check rejects every request as
  ERR_FORBIDDEN regardless of implementation correctness.

- Respondent is ENTITY-BACKED with the same rules as Petitioner —
  X-User-ID is the Party.id whose role is RESPONDENT.

- AttorneyOfRecord is OPAQUE. PRD §2.1: "When X-User-Role is
  AttorneyOfRecord, X-User-ID is an opaque attorney identifier;
  ownership is established by comparing X-User-ID to the
  counsel_user_id of the Party the attorney is acting on behalf of."
  Tests that want an attorney to act on behalf of a Party must first
  create the case with that Party's counsel_user_id set to the
  attorney's X-User-ID (e.g., ATTORNEY_FOR_PETITIONER_ID).

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
JUDGE_ID: str = "judge-001"
JUDGE_ID_ALT: str = "judge-002"

MEDIATOR_ID: str = "mediator-001"
MEDIATOR_ID_ALT: str = "mediator-002"

PLATFORM_ADMIN_ID: str = "admin-001"
PLATFORM_ADMIN_ID_ALT: str = "admin-002"

# Attorney identifiers. AttorneyOfRecord is OPAQUE — the value here is
# what would be stored in Party.counsel_user_id on case creation. To
# have an attorney successfully act on behalf of a party, the case
# payload's petitioner.counsel_user_id (or respondent.counsel_user_id)
# must equal ATTORNEY_FOR_PETITIONER_ID (or ATTORNEY_FOR_RESPONDENT_ID).
ATTORNEY_FOR_PETITIONER_ID: str = "attorney-pet-001"
ATTORNEY_FOR_RESPONDENT_ID: str = "attorney-res-001"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
# Safe only for header-missing / role-mismatch / NotFound paths.
PETITIONER_FALLBACK_ID: str = "fallback-petitioner-1"
RESPONDENT_FALLBACK_ID: str = "fallback-respondent-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque Judge — shared constant is canonical.
    "judge_headers": build_user_headers(JUDGE_ID, "Judge"),
    "judge_headers_alt": build_user_headers(JUDGE_ID_ALT, "Judge"),
    # Opaque Mediator — shared constant is canonical.
    "mediator_headers": build_user_headers(MEDIATOR_ID, "Mediator"),
    "mediator_headers_alt": build_user_headers(MEDIATOR_ID_ALT, "Mediator"),
    # Opaque PlatformAdmin — shared constant is canonical.
    "admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "admin_headers_alt": build_user_headers(
        PLATFORM_ADMIN_ID_ALT, "PlatformAdmin",
    ),
    # AttorneyOfRecord is opaque BUT the X-User-ID must equal the
    # Party.counsel_user_id pinned on the case. Shared constant is
    # canonical when paired with the matching counsel_user_id in the
    # case payload.
    "attorney_for_petitioner_headers": build_user_headers(
        ATTORNEY_FOR_PETITIONER_ID, "AttorneyOfRecord",
    ),
    "attorney_for_respondent_headers": build_user_headers(
        ATTORNEY_FOR_RESPONDENT_ID, "AttorneyOfRecord",
    ),
    # Entity-backed Petitioner / Respondent fallbacks — DO NOT use for
    # ownership-gated calls. Safe only for header-missing /
    # role-mismatch / 404 paths.
    "petitioner_fallback_headers": build_user_headers(
        PETITIONER_FALLBACK_ID, "Petitioner",
    ),
    "respondent_fallback_headers": build_user_headers(
        RESPONDENT_FALLBACK_ID, "Respondent",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Petitioner and
# Respondent. The runtime Party.id minted by POST /cases is the value
# the implementation will compare against in ownership checks.
# ---------------------------------------------------------------------------
def make_petitioner_headers(party_id: str) -> Dict[str, str]:
    """For Petitioner (entity_backed:Party).

    PRD §2.1: "When X-User-Role is Petitioner, X-User-ID is the id of
    the acting Party row (specifically, the Party on the targeted case
    whose role is PETITIONER). Ownership checks on any resource that
    references a Party ... compare the resource's party foreign-key
    field to X-User-ID."

    Pass the actual petitioner Party.id (i.e.,
    case["petitioner_party_id"]). Every Petitioner-acting ownership-
    gated call MUST use this builder, never the shared
    PETITIONER_FALLBACK_ID constant.
    """
    return build_user_headers(party_id, "Petitioner")


def make_respondent_headers(party_id: str) -> Dict[str, str]:
    """For Respondent (entity_backed:Party).

    PRD §2.1: "When X-User-Role is Respondent, X-User-ID is the id of
    the acting Party row (the Party on the targeted case whose role is
    RESPONDENT). Ownership checks are made the same way."

    Pass the actual respondent Party.id (i.e.,
    case["respondent_party_id"]).
    """
    return build_user_headers(party_id, "Respondent")


def make_attorney_headers(attorney_id: str) -> Dict[str, str]:
    """For AttorneyOfRecord (opaque).

    PRD §2.1: "When X-User-Role is AttorneyOfRecord, X-User-ID is an
    opaque attorney identifier; ownership is established by comparing
    X-User-ID to the counsel_user_id of the Party the attorney is
    acting on behalf of."

    To make this attorney act on behalf of a party, the case payload's
    petitioner.counsel_user_id (or respondent.counsel_user_id) must
    equal the attorney_id passed here.
    """
    return build_user_headers(attorney_id, "AttorneyOfRecord")


def make_judge_headers(judge_id: str) -> Dict[str, str]:
    """For Judge (opaque)."""
    return build_user_headers(judge_id, "Judge")


def make_mediator_headers(mediator_id: str) -> Dict[str, str]:
    """For Mediator (opaque)."""
    return build_user_headers(mediator_id, "Mediator")


def make_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlatformAdmin (opaque)."""
    return build_user_headers(admin_id, "PlatformAdmin")


__all__ = [
    "JUDGE_ID",
    "JUDGE_ID_ALT",
    "MEDIATOR_ID",
    "MEDIATOR_ID_ALT",
    "PLATFORM_ADMIN_ID",
    "PLATFORM_ADMIN_ID_ALT",
    "ATTORNEY_FOR_PETITIONER_ID",
    "ATTORNEY_FOR_RESPONDENT_ID",
    "PETITIONER_FALLBACK_ID",
    "RESPONDENT_FALLBACK_ID",
    "TEST_USERS",
    "make_petitioner_headers",
    "make_respondent_headers",
    "make_attorney_headers",
    "make_judge_headers",
    "make_mediator_headers",
    "make_admin_headers",
]
