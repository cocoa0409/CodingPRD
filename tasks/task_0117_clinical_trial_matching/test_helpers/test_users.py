"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- PrincipalInvestigator, IRBReviewer, StudyCoordinator are OPAQUE. PRD
  §2.1: "For the three operator roles — PrincipalInvestigator,
  IRBReviewer, and StudyCoordinator — X-User-ID is an opaque operator
  identifier not tied to any persisted entity record." Shared headers
  in TEST_USERS are canonical for these three roles, BUT the SoD check
  PRD §2.5 requires that the acting IRBReviewer's X-User-ID is NOT
  equal to the trial's recorded created_by_user_id. Tests that exercise
  IRB approval MUST use a PI id distinct from the reviewer's id. The
  shared PI / IRBReviewer constants below are deliberately distinct so
  the default pair satisfies SoD. A second-PI builder is also exposed
  for tests that need to provoke SoD VIOLATION (reviewer == creator).

- Participant_self is ENTITY-BACKED. PRD §2.1: "For Participant_self,
  X-User-ID is the id of the acting Participant. Ownership checks on
  any participant-scoped resource compare the path-bound participant_id
  to X-User-ID: Participant_self may sign consent, withdraw, read their
  own participant record, list their own visits, and list their own
  payments only when participant_id == X-User-ID."

  Every Participant_self-driven call whose success depends on owning
  the targeted participant resource MUST mint headers via
  make_participant_self_headers(participant["id"]) — never via a shared
  constant. Falling back to a shared constant for entity-backed roles
  reproduces the canonical bug: a literal "fallback-participant-1"
  string never equals any real Participant.id, so every ownership check
  rejects every request, cascading "Setup failed" into dozens of tests
  downstream.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
# ---------------------------------------------------------------------------
PRINCIPAL_INVESTIGATOR_ID = "pi-001"
PRINCIPAL_INVESTIGATOR_ID_ALT = "pi-002"

IRB_REVIEWER_ID = "irb-001"
IRB_REVIEWER_ID_ALT = "irb-002"

STUDY_COORDINATOR_ID = "coord-001"
STUDY_COORDINATOR_ID_ALT = "coord-002"

# Entity-backed fallback id — DO NOT use for ownership-gated calls.
PARTICIPANT_SELF_FALLBACK_ID = "fallback-participant-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # PrincipalInvestigator — opaque.
    "pi_headers": build_user_headers(
        PRINCIPAL_INVESTIGATOR_ID, "PrincipalInvestigator",
    ),
    "pi_headers_alt": build_user_headers(
        PRINCIPAL_INVESTIGATOR_ID_ALT, "PrincipalInvestigator",
    ),
    # IRBReviewer — opaque. Distinct from the default PI to satisfy SoD
    # (PRD §2.5) by default.
    "irb_reviewer_headers": build_user_headers(
        IRB_REVIEWER_ID, "IRBReviewer",
    ),
    "irb_reviewer_headers_alt": build_user_headers(
        IRB_REVIEWER_ID_ALT, "IRBReviewer",
    ),
    # StudyCoordinator — opaque.
    "study_coordinator_headers": build_user_headers(
        STUDY_COORDINATOR_ID, "StudyCoordinator",
    ),
    "study_coordinator_headers_alt": build_user_headers(
        STUDY_COORDINATOR_ID_ALT, "StudyCoordinator",
    ),
    # Participant_self — entity-backed FALLBACK. Safe only for
    # auth/role-mismatch tests and tests that DO NOT exercise ownership.
    # Ownership-gated calls MUST use make_participant_self_headers.
    "participant_self_fallback_headers": build_user_headers(
        PARTICIPANT_SELF_FALLBACK_ID, "Participant_self",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — REQUIRED for entity-backed Participant_self.
# ---------------------------------------------------------------------------
def make_participant_self_headers(participant_id: str) -> Dict[str, str]:
    """For Participant_self (entity_backed:Participant). Pass the actual
    Participant.id of the acting participant.

    PRD §2.1: "For Participant_self, X-User-ID is the id of the acting
    Participant. Ownership checks on any participant-scoped resource
    compare the path-bound participant_id to X-User-ID: Participant_self
    may sign consent, withdraw, read their own participant record, list
    their own visits, and list their own payments only when
    participant_id == X-User-ID."

    Every Participant_self-driven call whose success depends on owning
    the targeted Participant MUST use this builder, not the shared
    PARTICIPANT_SELF_FALLBACK_ID constant.
    """
    return build_user_headers(participant_id, "Participant_self")


# ---------------------------------------------------------------------------
# Opaque-role per-id builders — used when a test needs a SECOND distinct
# operator id for the same role (e.g., SoD: a PI creates a trial and a
# DIFFERENT PI id is then used as the IRB reviewer of that same trial).
# ---------------------------------------------------------------------------
def make_pi_headers(user_id: str) -> Dict[str, str]:
    """For PrincipalInvestigator (opaque). PRD §2.5: "Each Trial row
    records the X-User-ID of its creator as created_by_user_id at the
    moment a PrincipalInvestigator calls trial creation." Use this
    builder to mint a SPECIFIC creator id when SoD pairing matters."""
    return build_user_headers(user_id, "PrincipalInvestigator")


def make_irb_reviewer_headers(user_id: str) -> Dict[str, str]:
    """For IRBReviewer (opaque). PRD §2.5: "When an IRBReviewer later
    submits a review decision, the reviewer's X-User-ID is compared to
    that recorded created_by_user_id; if they match, the request is
    rejected with ERR_SOD_VIOLATION at HTTP 403." Use this builder to
    mint a SPECIFIC reviewer id when SoD pairing matters (in particular,
    to PROVOKE the violation by deliberately reusing the PI's id)."""
    return build_user_headers(user_id, "IRBReviewer")


def make_study_coordinator_headers(user_id: str) -> Dict[str, str]:
    """For StudyCoordinator (opaque). Any non-empty operator id works."""
    return build_user_headers(user_id, "StudyCoordinator")


__all__ = [
    "PRINCIPAL_INVESTIGATOR_ID",
    "PRINCIPAL_INVESTIGATOR_ID_ALT",
    "IRB_REVIEWER_ID",
    "IRB_REVIEWER_ID_ALT",
    "STUDY_COORDINATOR_ID",
    "STUDY_COORDINATOR_ID_ALT",
    "PARTICIPANT_SELF_FALLBACK_ID",
    "TEST_USERS",
    "make_participant_self_headers",
    "make_pi_headers",
    "make_irb_reviewer_headers",
    "make_study_coordinator_headers",
]
