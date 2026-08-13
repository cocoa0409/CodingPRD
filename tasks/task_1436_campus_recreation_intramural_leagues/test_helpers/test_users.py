"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque operator roles (RecAdmin, LeagueCoordinator,
# FacilityManager): the server does not compare their X-User-ID to any entity
# id, so a fixed identifier is canonical.
# Member and Staff are entity-backed: use the per-instance builders below
# whenever a call is ownership-gated (self-service, captain, assignee,
# instructor checks).
TEST_USERS = {
    "rec_admin_headers": build_user_headers("test-rec-admin-1", "RecAdmin"),
    "league_coordinator_headers": build_user_headers(
        "test-league-coordinator-1", "LeagueCoordinator"
    ),
    "facility_manager_headers": build_user_headers(
        "test-facility-manager-1", "FacilityManager"
    ),
    # Fallbacks for non-ownership calls only; never use for self-service or
    # captain-gated operations.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "staff_headers": build_user_headers("test-staff-1", "Staff"),
}


def make_member_headers(user_id: str) -> dict:
    """Member is entity-backed: pass the acting Member.id as user_id."""
    return build_user_headers(user_id, "Member")


def make_staff_headers(user_id: str) -> dict:
    """Staff is entity-backed: pass the acting Staff.id as user_id."""
    return build_user_headers(user_id, "Staff")
