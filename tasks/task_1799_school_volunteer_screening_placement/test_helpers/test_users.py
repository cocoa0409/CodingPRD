"""Pre-built role headers for every role in the PRD.

DistrictCoordinator and CampusAdmin are opaque identities: X-User-ID is not
tied to any persisted entity. Volunteer is entity-backed by the Volunteer
resource (X-User-ID is the acting Volunteer's id); ownership-gated calls MUST
use make_volunteer_headers() with the real Volunteer id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "coordinator_headers": build_user_headers("test-coordinator-1", "DistrictCoordinator"),
    "campus_admin_headers": build_user_headers("test-campus-admin-1", "CampusAdmin"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
}


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "DistrictCoordinator")


def make_campus_admin_headers(user_id: str = "test-campus-admin-1") -> dict:
    return build_user_headers(user_id, "CampusAdmin")


def make_volunteer_headers(volunteer_id: str) -> dict:
    """For Volunteer (entity_backed:Volunteer). Pass the acting Volunteer's id
    whenever the call is ownership-gated (own record reads, placement requests,
    hour logging, check-in/check-out, own cancellations)."""
    return build_user_headers(volunteer_id, "Volunteer")
