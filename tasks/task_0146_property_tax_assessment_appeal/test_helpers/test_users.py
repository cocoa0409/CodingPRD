"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Assessor and Treasurer are OPAQUE. PRD §2.1: "When X-User-Role is
  Assessor, X-User-ID is an opaque operator identifier not tied to any
  persisted entity." Same for Treasurer. Shared constants are
  canonical.

- HearingOfficer is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  HearingOfficer, X-User-ID is the id of the acting HearingOfficer
  entity; ownership and identity checks compare Hearing.officer_id
  against X-User-ID directly." Every HearingOfficer call whose success
  depends on owning the targeted resource (conduct, decide) MUST mint
  headers via make_hearing_officer_headers(officer["id"]).

- Owner is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Owner,
  X-User-ID is the id of the acting Owner entity; for every
  owner-scoped write ... the server compares Property.owner_id against
  X-User-ID and rejects mismatches with ERR_OWNERSHIP_MISMATCH." Every
  Owner call whose success depends on owning the targeted Property
  MUST mint headers via make_owner_headers(owner["id"]).

Falling back to a shared constant for entity-backed roles reproduces
the canonical bug: the literal "fallback-owner-1" never equals any real
Owner.id, so every ownership check rejects every request as
ERR_OWNERSHIP_MISMATCH.

The shared *_FALLBACK_ID constants below are ONLY safe for tests that
do not exercise ownership: header-missing tests, role-not-permitted
tests, 404-on-non-existent-resource tests, and opaque-role calls.

SEGREGATION OF DUTIES — PRD §2.8: "the HearingOfficer who is recorded
as the presiding officer (via Hearing.officer_id) must not be the same
user who issued the underlying Assessment." Tests that intentionally
trigger ERR_BOE_OFFICER_CONFLICT will construct an Assessor header
whose X-User-ID equals the officer's HearingOfficer.id; the fixtures
expose ASSESSOR_ID and ASSESSOR_ID_ALT so the default Assessor identity
is distinct from any minted HearingOfficer.id.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
ASSESSOR_ID = "assessor-001"
ASSESSOR_ID_ALT = "assessor-002"

TREASURER_ID = "treasurer-001"
TREASURER_ID_ALT = "treasurer-002"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
OWNER_FALLBACK_ID = "fallback-owner-1"
HEARING_OFFICER_FALLBACK_ID = "fallback-officer-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque Assessor — shared constant is canonical.
    "assessor_headers": build_user_headers(ASSESSOR_ID, "Assessor"),
    "assessor_headers_alt": build_user_headers(
        ASSESSOR_ID_ALT, "Assessor",
    ),
    # Opaque Treasurer — shared constant is canonical.
    "treasurer_headers": build_user_headers(TREASURER_ID, "Treasurer"),
    "treasurer_headers_alt": build_user_headers(
        TREASURER_ID_ALT, "Treasurer",
    ),
    # Entity-backed Owner fallback — DO NOT use for ownership-gated calls.
    "owner_fallback_headers": build_user_headers(
        OWNER_FALLBACK_ID, "Owner",
    ),
    # Entity-backed HearingOfficer fallback — DO NOT use for officer
    # identity-gated calls (conduct, decide).
    "hearing_officer_fallback_headers": build_user_headers(
        HEARING_OFFICER_FALLBACK_ID, "HearingOfficer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed roles.
# ---------------------------------------------------------------------------
def make_owner_headers(owner_id: str) -> Dict[str, str]:
    """For Owner (entity_backed:Owner). PRD §2.1: "When X-User-Role is
    Owner, X-User-ID is the id of the acting Owner entity; for every
    owner-scoped write ... the server compares Property.owner_id
    against X-User-ID and rejects mismatches with
    ERR_OWNERSHIP_MISMATCH."

    Every Owner call whose success depends on owning the targeted
    Property MUST use this builder with the real Owner.id minted by
    POST /owners — NOT the shared OWNER_FALLBACK_ID.
    """
    return build_user_headers(owner_id, "Owner")


def make_hearing_officer_headers(officer_id: str) -> Dict[str, str]:
    """For HearingOfficer (entity_backed:HearingOfficer). PRD §2.1:
    "When X-User-Role is HearingOfficer, X-User-ID is the id of the
    acting HearingOfficer entity; ownership and identity checks compare
    Hearing.officer_id against X-User-ID directly."

    Every HearingOfficer call (conduct, decide) MUST use this builder
    with the real HearingOfficer.id captured on the Hearing — NOT the
    shared HEARING_OFFICER_FALLBACK_ID.
    """
    return build_user_headers(officer_id, "HearingOfficer")


def make_assessor_headers(assessor_id: str) -> Dict[str, str]:
    """For Assessor (opaque). PRD §2.1: "When X-User-Role is Assessor,
    X-User-ID is an opaque operator identifier not tied to any
    persisted entity. The server may record it (for example, as the
    user who issued an Assessment for later segregation-of-duties
    checks) but does not compare it against any entity's id."

    Tests that need to model an Assessor whose X-User-ID equals a
    HearingOfficer.id (to trigger ERR_BOE_OFFICER_CONFLICT) construct
    headers via this builder.
    """
    return build_user_headers(assessor_id, "Assessor")


def make_treasurer_headers(treasurer_id: str) -> Dict[str, str]:
    """For Treasurer (opaque). Any non-empty operator id is fine."""
    return build_user_headers(treasurer_id, "Treasurer")


__all__ = [
    "ASSESSOR_ID",
    "ASSESSOR_ID_ALT",
    "TREASURER_ID",
    "TREASURER_ID_ALT",
    "OWNER_FALLBACK_ID",
    "HEARING_OFFICER_FALLBACK_ID",
    "TEST_USERS",
    "make_owner_headers",
    "make_hearing_officer_headers",
    "make_assessor_headers",
    "make_treasurer_headers",
]
