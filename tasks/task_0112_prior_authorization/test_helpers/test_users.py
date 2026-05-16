"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Provider is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Provider,
  X-User-ID is the id of the acting Provider entity. Ownership checks
  on any resource that references a Provider (for example, an
  AuthorizationRequest whose provider_id identifies the requesting
  practice) compare the resource's foreign-key field to X-User-ID. A
  Provider may only act on, and may only list, authorization requests
  whose provider_id equals X-User-ID."

  Every Provider-driven call whose success depends on owning the targeted
  AuthorizationRequest / ClinicalEvidence / PeerToPeerReview / Appeal
  MUST mint headers via make_provider_headers(provider["id"]) — never
  via the PROVIDER_FALLBACK_ID shared constant. Falling back to the
  shared constant for entity-backed roles reproduces the canonical bug:
  the literal "fallback-provider-1" never equals any real Provider.id,
  so every ownership check rejects every request, cascading "Setup
  failed" into dozens of tests downstream.

- PlatformAdmin, InitialReviewer, MedicalDirector, ExternalReviewer,
  and PayerReviewer are all OPAQUE. PRD §2.1: "When X-User-Role is
  PlatformAdmin, InitialReviewer, MedicalDirector, ExternalReviewer,
  or PayerReviewer, X-User-ID is an opaque operator identifier not tied
  to any persisted entity. The server may record it for audit purposes
  (for example, as payer_reviewer_id on a PeerToPeerReview when a
  transition writes it) but does not compare it to any entity's id."
  Shared constants in TEST_USERS are canonical for these five roles.

The shared PROVIDER_FALLBACK_ID constant is ONLY safe for tests that
DO NOT exercise ownership (auth-missing, role-mismatch, NotFound on
unrelated paths). Ownership-gated calls MUST use the per-instance
builder.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PLATFORM_ADMIN_ID = "admin-001"
PLATFORM_ADMIN_ID_ALT = "admin-002"

INITIAL_REVIEWER_ID = "init-reviewer-001"
INITIAL_REVIEWER_ID_ALT = "init-reviewer-002"

MEDICAL_DIRECTOR_ID = "med-director-001"
MEDICAL_DIRECTOR_ID_ALT = "med-director-002"

EXTERNAL_REVIEWER_ID = "ext-reviewer-001"
EXTERNAL_REVIEWER_ID_ALT = "ext-reviewer-002"

PAYER_REVIEWER_ID = "payer-reviewer-001"
PAYER_REVIEWER_ID_ALT = "payer-reviewer-002"

# Entity-backed fallback id — DO NOT use for ownership-gated calls.
PROVIDER_FALLBACK_ID = "fallback-provider-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # PlatformAdmin — opaque
    "admin_headers": build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin"),
    "admin_headers_alt": build_user_headers(
        PLATFORM_ADMIN_ID_ALT, "PlatformAdmin",
    ),
    # InitialReviewer — opaque
    "initial_reviewer_headers": build_user_headers(
        INITIAL_REVIEWER_ID, "InitialReviewer",
    ),
    "initial_reviewer_headers_alt": build_user_headers(
        INITIAL_REVIEWER_ID_ALT, "InitialReviewer",
    ),
    # MedicalDirector — opaque
    "medical_director_headers": build_user_headers(
        MEDICAL_DIRECTOR_ID, "MedicalDirector",
    ),
    "medical_director_headers_alt": build_user_headers(
        MEDICAL_DIRECTOR_ID_ALT, "MedicalDirector",
    ),
    # ExternalReviewer — opaque
    "external_reviewer_headers": build_user_headers(
        EXTERNAL_REVIEWER_ID, "ExternalReviewer",
    ),
    "external_reviewer_headers_alt": build_user_headers(
        EXTERNAL_REVIEWER_ID_ALT, "ExternalReviewer",
    ),
    # PayerReviewer — opaque
    "payer_reviewer_headers": build_user_headers(
        PAYER_REVIEWER_ID, "PayerReviewer",
    ),
    "payer_reviewer_headers_alt": build_user_headers(
        PAYER_REVIEWER_ID_ALT, "PayerReviewer",
    ),
    # Provider — entity-backed FALLBACK. Safe only for auth/role/NotFound
    # paths; ownership-gated calls MUST use make_provider_headers.
    "provider_fallback_headers": build_user_headers(
        PROVIDER_FALLBACK_ID, "Provider",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — REQUIRED for entity-backed Provider.
# ---------------------------------------------------------------------------
def make_provider_headers(provider_id: str) -> Dict[str, str]:
    """For Provider (entity_backed:Provider). Pass the actual Provider.id
    of the acting practice.

    PRD §2.1: "When X-User-Role is Provider, X-User-ID is the id of the
    acting Provider entity. Ownership checks on any resource that
    references a Provider (for example, an AuthorizationRequest whose
    provider_id identifies the requesting practice) compare the
    resource's foreign-key field to X-User-ID. A Provider may only act
    on, and may only list, authorization requests whose provider_id
    equals X-User-ID."

    Every Provider-driven call whose success depends on owning the
    targeted AuthorizationRequest / ClinicalEvidence / PeerToPeerReview
    / Appeal MUST use this builder, not the shared
    PROVIDER_FALLBACK_ID constant.
    """
    return build_user_headers(provider_id, "Provider")


def make_admin_headers(admin_id: str) -> Dict[str, str]:
    """For PlatformAdmin (opaque). Any non-empty operator id is fine."""
    return build_user_headers(admin_id, "PlatformAdmin")


def make_initial_reviewer_headers(user_id: str) -> Dict[str, str]:
    """For InitialReviewer (opaque). Any non-empty operator id is fine."""
    return build_user_headers(user_id, "InitialReviewer")


def make_medical_director_headers(user_id: str) -> Dict[str, str]:
    """For MedicalDirector (opaque). Any non-empty operator id is fine."""
    return build_user_headers(user_id, "MedicalDirector")


def make_external_reviewer_headers(user_id: str) -> Dict[str, str]:
    """For ExternalReviewer (opaque). Any non-empty operator id is fine."""
    return build_user_headers(user_id, "ExternalReviewer")


def make_payer_reviewer_headers(user_id: str) -> Dict[str, str]:
    """For PayerReviewer (opaque). Any non-empty operator id is fine.

    PRD §2.1: "The server may record it for audit purposes (for example,
    as payer_reviewer_id on a PeerToPeerReview when a transition writes
    it) but does not compare it to any entity's id." Use this builder
    when a test needs a distinct PayerReviewer audit token (e.g., when
    P2P conflict checks must compare against a specific
    payer_reviewer_id supplied in the request body)."""
    return build_user_headers(user_id, "PayerReviewer")


__all__ = [
    "PLATFORM_ADMIN_ID",
    "PLATFORM_ADMIN_ID_ALT",
    "INITIAL_REVIEWER_ID",
    "INITIAL_REVIEWER_ID_ALT",
    "MEDICAL_DIRECTOR_ID",
    "MEDICAL_DIRECTOR_ID_ALT",
    "EXTERNAL_REVIEWER_ID",
    "EXTERNAL_REVIEWER_ID_ALT",
    "PAYER_REVIEWER_ID",
    "PAYER_REVIEWER_ID_ALT",
    "PROVIDER_FALLBACK_ID",
    "TEST_USERS",
    "make_provider_headers",
    "make_admin_headers",
    "make_initial_reviewer_headers",
    "make_medical_director_headers",
    "make_external_reviewer_headers",
    "make_payer_reviewer_headers",
]
