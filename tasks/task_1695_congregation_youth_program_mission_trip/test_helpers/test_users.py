"""Pre-built role headers for every role in the PRD.

ProgramDirector, TripLeader, Treasurer, ScholarshipReviewer, and Guardian are
opaque identities: X-User-ID is a stored operator string, never compared to an
entity id. A Guardian's ownership anchor is the stored `guardian_user_id`
string, so Guardian headers are built per guardian handle ("guardian-1", ...).

Chaperone is different (entity-backed): X-User-ID is the acting Chaperone
entity's id. Ownership-gated chaperone calls MUST use
make_chaperone_headers(chaperone["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for calls that do not exercise ownership.
TEST_USERS = {
    "director_headers": build_user_headers("director-1", "ProgramDirector"),
    "leader_headers": build_user_headers("leader-1", "TripLeader"),
    "treasurer_headers": build_user_headers("treasurer-1", "Treasurer"),
    "reviewer_headers": build_user_headers("reviewer-1", "ScholarshipReviewer"),
    # Guardian: shared fallback for non-ownership probes only.
    "guardian_headers": build_user_headers("guardian-1", "Guardian"),
    # Chaperone (entity_backed): fallback for role-denial probes only.
    "chaperone_headers": build_user_headers(
        "11111111-1111-4111-8111-111111111111", "Chaperone"),
}


def make_director_headers(user_id: str = "director-1") -> dict:
    return build_user_headers(user_id, "ProgramDirector")


def make_leader_headers(user_id: str = "leader-1") -> dict:
    return build_user_headers(user_id, "TripLeader")


def make_treasurer_headers(user_id: str = "treasurer-1") -> dict:
    return build_user_headers(user_id, "Treasurer")


def make_reviewer_headers(user_id: str = "reviewer-1") -> dict:
    return build_user_headers(user_id, "ScholarshipReviewer")


def make_guardian_headers(guardian_user_id: str) -> dict:
    """Guardian ownership is anchored on the guardian_user_id string; pass the
    same handle used when the participant/registration was created."""
    return build_user_headers(guardian_user_id, "Guardian")


def make_chaperone_headers(chaperone_id: str) -> dict:
    """Chaperone is entity-backed: X-User-ID must be the Chaperone record's id
    whenever the call is ownership-gated (respond, read own record/checks)."""
    return build_user_headers(chaperone_id, "Chaperone")
