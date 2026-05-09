"""Pre-built role headers for every role in the PRD.

PRD §2.1 distinguishes roles by identity binding:

- Organizer, DisciplinaryOfficer, DopingOfficer, AppealsBoard: opaque —
  X-User-ID is not compared to any persisted entity row.
- Referee: entity-backed on Referee — when X-User-Role is `Referee`,
  PRD §2.1 mandates that X-User-ID equal the acting Referee.id. Ownership
  checks (e.g., on `submitted_by_assignment_id` resolving to a
  RefereeAssignment whose `referee_id` matches X-User-ID) compare the
  resource's foreign key to X-User-ID.
- Participant: entity-backed on Participant — X-User-ID must equal
  Participant.id. Filing a dispute or appeal (Dispute.filed_by_participant_id,
  Appeal.filed_by_user_id) compares the body field to X-User-ID.

For every entity-backed role, ownership-gated calls MUST use the
per-instance builder make_<role>_headers(actual_entity_id). The shared
TEST_USERS constants exist only as a fallback for tests whose success
does NOT depend on the caller owning a specific resource (e.g.,
ERR_VALIDATION on bad payload, ERR_NOT_FOUND on missing path,
ERR_FORBIDDEN where the role is rejected before identity check).
"""
from __future__ import annotations
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles; for entity-backed roles, use
# only when the test does NOT exercise an ownership comparison.
TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — shared constants are canonical (PRD §2.1).
    "organizer_headers": build_user_headers("organizer-001", "Organizer"),
    "organizer_headers_alt": build_user_headers("organizer-002", "Organizer"),
    "disciplinary_headers": build_user_headers("disc-001", "DisciplinaryOfficer"),
    "doping_headers": build_user_headers("dop-001", "DopingOfficer"),
    "doping_headers_alt": build_user_headers("dop-002", "DopingOfficer"),
    "appeals_headers": build_user_headers("appeals-001", "AppealsBoard"),

    # Entity-backed roles — shared constants are FALLBACK for non-ownership tests.
    # Tests that succeed only when ownership matches must use the builders below.
    "referee_headers": build_user_headers("referee-fallback-001", "Referee"),
    "participant_headers": build_user_headers("participant-fallback-001", "Participant"),
}


# --- Per-instance builders for entity-backed roles ---
# Each builder threads the actual entity id through X-User-ID so that
# ownership comparisons (PRD §2.1) succeed for real-world flows.

def make_organizer_headers(operator_id: str = "organizer-001") -> Dict[str, str]:
    """Organizer headers; identity is opaque per PRD §2.1.

    Optional operator_id allows distinguishing two organizer operators
    (e.g., for AuditLog.actor_user_id assertions or concurrency tests where
    two organizers race the same /complete call). The server does not
    compare X-User-ID to any entity id for this role.
    """
    return build_user_headers(operator_id, "Organizer")


def make_disciplinary_headers(operator_id: str = "disc-001") -> Dict[str, str]:
    """DisciplinaryOfficer headers; identity is opaque per PRD §2.1."""
    return build_user_headers(operator_id, "DisciplinaryOfficer")


def make_doping_headers(operator_id: str = "dop-001") -> Dict[str, str]:
    """DopingOfficer headers; identity is opaque, but PRD §3.7 segregation
    of duties compares X-User-ID byte-equal to the actor_user_id stored on
    the RECEIVE chain_log entry. Tests that exercise this rule must hand
    distinct operator_id values to the receiver and the lab-result poster.
    """
    return build_user_headers(operator_id, "DopingOfficer")


def make_appeals_headers(operator_id: str = "appeals-001") -> Dict[str, str]:
    """AppealsBoard headers; identity is opaque per PRD §2.1."""
    return build_user_headers(operator_id, "AppealsBoard")


def make_referee_headers(referee_id: str) -> Dict[str, str]:
    """Referee headers. PRD §2.1: 'When X-User-Role is Referee, X-User-ID
    is the id of the acting Referee row; ownership checks on any resource
    that references a Referee (notably RefereeAssignment.referee_id)
    compare the resource's foreign-key field to X-User-ID.'

    Pass the actual Referee.id whenever the request is ownership-gated.
    """
    return build_user_headers(referee_id, "Referee")


def make_participant_headers(participant_id: str) -> Dict[str, str]:
    """Participant headers. PRD §2.1: 'When X-User-Role is Participant,
    X-User-ID is the id of the acting Participant row; ownership checks on
    any resource that references a Participant (notably
    Dispute.filed_by_participant_id and Appeal.filed_by_user_id) compare
    the resource's foreign-key field to X-User-ID.'

    Pass the actual Participant.id whenever the request is ownership-gated.
    """
    return build_user_headers(participant_id, "Participant")


__all__ = [
    "TEST_USERS",
    "make_organizer_headers",
    "make_disciplinary_headers",
    "make_doping_headers",
    "make_appeals_headers",
    "make_referee_headers",
    "make_participant_headers",
]
