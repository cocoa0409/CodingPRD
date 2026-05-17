"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Custodian / ComplianceOfficer / Auditor are OPAQUE. PRD §2.1:
  "When X-User-Role is Custodian, X-User-ID is an opaque operator
  identifier not tied to any persisted entity. The server records it
  (for example, as approver_role_id on a ConversionRequest when a
  custodian approves it) but does not compare it to any entity's id.
  The same applies when X-User-Role is ComplianceOfficer or Auditor:
  in both cases X-User-ID is an opaque operator identifier that the
  server may record but does not match against any participant id."
  Shared constants are canonical for these operator-only roles.

- Participant is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  Participant, X-User-ID is the id of the acting Participant;
  ownership checks on any resource that references a Participant
  (directly through participant_id on an Account or
  ConversionRequest, or indirectly through an Account's
  participant_id) compare the resource's foreign-key field to
  X-User-ID."

  Every Participant-acting call whose success depends on owning the
  targeted resource MUST mint headers via
  make_participant_headers(participant["id"]) — never via the shared
  PARTICIPANT_FALLBACK_ID constant. Falling back to the shared
  constant for entity-backed roles reproduces the canonical bug: the
  literal "fallback-participant-1" never equals any real
  Participant.id, so every ownership check rejects every request as
  ERR_NOT_FOUND (PRD §2.1 routes scoped to 'self only' return
  ERR_NOT_FOUND on cross-tenant access).

The shared PARTICIPANT_FALLBACK_ID constant is ONLY safe for tests
that DO NOT exercise ownership (header-missing, role-mismatch,
404-on-non-existent path).

SEGREGATION OF DUTIES — PRD §2.1: a Custodian whose X-User-ID equals
the requesting participant's id cannot approve that participant's
own conversion request. Two distinct custodian ids let tests model a
clean (non-equal) custodian for normal approvals and a deliberately
equal id for ERR_SEGREGATION_VIOLATION assertions.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
CUSTODIAN_ID = "custodian-001"
CUSTODIAN_ID_ALT = "custodian-002"

COMPLIANCE_OFFICER_ID = "compliance-001"
COMPLIANCE_OFFICER_ID_ALT = "compliance-002"

AUDITOR_ID = "auditor-001"

# Entity-backed fallback id — DO NOT use for ownership-gated calls.
PARTICIPANT_FALLBACK_ID = "fallback-participant-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque Custodian — shared constant is canonical for non-segregation
    # operator calls.
    "custodian_headers": build_user_headers(CUSTODIAN_ID, "Custodian"),
    "custodian_headers_alt": build_user_headers(
        CUSTODIAN_ID_ALT, "Custodian",
    ),
    # Opaque ComplianceOfficer — shared constant is canonical.
    "compliance_headers": build_user_headers(
        COMPLIANCE_OFFICER_ID, "ComplianceOfficer",
    ),
    "compliance_headers_alt": build_user_headers(
        COMPLIANCE_OFFICER_ID_ALT, "ComplianceOfficer",
    ),
    # Opaque Auditor — shared constant is canonical.
    "auditor_headers": build_user_headers(AUDITOR_ID, "Auditor"),
    # Entity-backed Participant fallback — DO NOT use for
    # ownership-gated calls. Safe only for header-missing / role-
    # mismatch / NotFound paths.
    "participant_fallback_headers": build_user_headers(
        PARTICIPANT_FALLBACK_ID, "Participant",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed Participant.
# The runtime Participant.id minted by POST /participants is the value
# the implementation will compare against in ownership checks
# (Account.participant_id, ConversionRequest.participant_id, etc.).
# ---------------------------------------------------------------------------
def make_participant_headers(participant_id: str) -> Dict[str, str]:
    """For Participant (entity_backed:Participant). Pass the actual
    Participant.id of the acting participant.

    PRD §2.1: "When X-User-Role is Participant, X-User-ID is the id of
    the acting Participant; ownership checks on any resource that
    references a Participant ... compare the resource's foreign-key
    field to X-User-ID. A Participant may only act on their own
    accounts, their own conversion requests, their own beneficiary
    claims, and their own 1099-R forms."

    Every Participant-driven call whose success depends on owning the
    targeted resource MUST use this builder, not the shared
    PARTICIPANT_FALLBACK_ID constant.
    """
    return build_user_headers(participant_id, "Participant")


def make_custodian_headers(custodian_id: str) -> Dict[str, str]:
    """For Custodian (opaque). Any non-empty operator id is fine; this
    builder exists so tests that want a distinct custodian id (for
    audit-token discrimination, segregation-of-duties scenarios where
    X-User-ID is set equal to a participant id, or two-custodian race
    tests) can supply one without relying on a single shared constant.
    """
    return build_user_headers(custodian_id, "Custodian")


def make_compliance_headers(compliance_id: str) -> Dict[str, str]:
    """For ComplianceOfficer (opaque)."""
    return build_user_headers(compliance_id, "ComplianceOfficer")


def make_auditor_headers(auditor_id: str) -> Dict[str, str]:
    """For Auditor (opaque)."""
    return build_user_headers(auditor_id, "Auditor")


__all__ = [
    "CUSTODIAN_ID",
    "CUSTODIAN_ID_ALT",
    "COMPLIANCE_OFFICER_ID",
    "COMPLIANCE_OFFICER_ID_ALT",
    "AUDITOR_ID",
    "PARTICIPANT_FALLBACK_ID",
    "TEST_USERS",
    "make_participant_headers",
    "make_custodian_headers",
    "make_compliance_headers",
    "make_auditor_headers",
]
