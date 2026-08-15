"""Pre-built role headers for every role in the PRD (§2.1).

ClubCoach and Proctor are entity-backed roles: their X-User-ID must equal the
acting Coach's id (PRD §2.1), so callers building an ownership-gated request
MUST use the per-instance builders with the real Coach.id. The shared constants
for those roles are safe only for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: X-User-ID is an operator identifier, not an entity id.
    "federation_admin_headers": build_user_headers("fed-admin-1", "FederationAdmin"),
    "treasurer_headers": build_user_headers("treasurer-1", "Treasurer"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
    # Entity-backed roles: shared constants are fallbacks for non-ownership tests only.
    "club_coach_headers": build_user_headers("test-coach-1", "ClubCoach"),
    "proctor_headers": build_user_headers("test-proctor-1", "Proctor"),
}


def make_club_coach_headers(user_id: str) -> dict:
    """ClubCoach is entity-backed by Coach: pass the acting Coach.id as user_id
    whenever the call is ownership-gated (own club's players, meets, entries,
    memberships, disputes, bids)."""
    return build_user_headers(user_id, "ClubCoach")


def make_proctor_headers(user_id: str) -> dict:
    """Proctor is entity-backed by Coach: pass the assigned Coach.id as user_id
    whenever confirming an assignment (X-User-ID must equal coach_id)."""
    return build_user_headers(user_id, "Proctor")
