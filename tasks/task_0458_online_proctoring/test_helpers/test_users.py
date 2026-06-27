"""Pre-built role headers for every role in the Online Proctoring PRD (§2.1).

Role identity binding (PRD §2.1):
  - SchedulingCoordinator: X-User-ID is an opaque operator id, not tied to any entity.
  - Proctor / ReviewOfficer: X-User-ID is the id of the acting Proctor record.
  - Candidate: X-User-ID is the id of the acting Candidate.

Shared constants are safe for the opaque SchedulingCoordinator and for tests whose
success does not depend on the caller owning the subject resource. For the
entity-backed roles, ownership-gated calls MUST thread the real entity id through
the per-instance builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "coordinator_headers": build_user_headers("test-coordinator-1", "SchedulingCoordinator"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "proctor_headers": build_user_headers("test-proctor-1", "Proctor"),
    "review_officer_headers": build_user_headers("test-review-officer-1", "ReviewOfficer"),
    "candidate_headers": build_user_headers("test-candidate-1", "Candidate"),
}


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    """SchedulingCoordinator (opaque). The id is recorded for audit only."""
    return build_user_headers(user_id, "SchedulingCoordinator")


def make_proctor_headers(user_id: str) -> dict:
    """For Proctor (entity_backed:Proctor). Pass the actual Proctor.id whenever the
    call is ownership-gated (raising flags, pausing/completing, opening escalations)."""
    return build_user_headers(user_id, "Proctor")


def make_review_officer_headers(user_id: str) -> dict:
    """For ReviewOfficer (entity_backed:Proctor — a proctor acting in a reviewing
    capacity). Pass the actual Proctor.id whenever segregation-of-duties or ownership
    is checked (claiming/deciding escalations, authorizing retakes)."""
    return build_user_headers(user_id, "ReviewOfficer")


def make_candidate_headers(user_id: str) -> dict:
    """For Candidate (entity_backed:Candidate). Pass the actual Candidate.id whenever
    the call is ownership-gated (verify-identity, check-in)."""
    return build_user_headers(user_id, "Candidate")
