"""Pre-built role headers for every role in the PRD (§2.1).

Four roles: StudioManager and FrontDesk are opaque operators; LashTech and Member
are entity-backed (X-User-ID must equal the acting entity's id for ownership checks).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque operator roles — shared constant is the canonical form
    "studio_manager_headers": build_user_headers("test-manager-1", "StudioManager"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    # entity_backed roles — shared constant is a fallback for non-ownership tests only
    "lash_tech_headers": build_user_headers("test-tech-1", "LashTech"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


# Per-instance builders — required for every entity_backed role.
def make_lash_tech_headers(user_id: str) -> dict:
    """For LashTech (entity_backed:LashTech). Pass the actual LashTech.id as user_id
    whenever the call is ownership-gated (e.g., completing the assigned tech's appointment)."""
    return build_user_headers(user_id, "LashTech")


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (e.g., booking/cancelling one's own appointment)."""
    return build_user_headers(user_id, "Member")
