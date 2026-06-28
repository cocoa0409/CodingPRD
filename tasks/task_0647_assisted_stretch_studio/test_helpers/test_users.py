"""Pre-built role headers for every role in the PRD.

Member and Flexologist are entity_backed: their X-User-ID must equal the
acting entity's id whenever an ownership check runs. FrontDesk and
StudioManager are opaque operators whose X-User-ID is not compared to any
entity, so the shared constants are the canonical form for them.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# entity ownership (e.g. 401/403/404/400 paths). For entity_backed roles the
# shared constant is ONLY a fallback for non-ownership tests; ownership-gated
# calls must use the per-instance builders below threaded with the real id.
TEST_USERS = {
    "member_headers": build_user_headers("test-member-1", "Member"),
    "flexologist_headers": build_user_headers("test-flexologist-1", "Flexologist"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDesk"),
    "studio_manager_headers": build_user_headers("test-manager-1", "StudioManager"),
}


# Per-instance builders — required for every entity_backed role.
def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_flexologist_headers(user_id: str) -> dict:
    """For Flexologist (entity_backed:Flexologist). Pass the actual Flexologist.id
    as user_id whenever the call is ownership-gated (e.g. complete on assigned
    booking)."""
    return build_user_headers(user_id, "Flexologist")


def make_front_desk_headers(user_id: str = "test-frontdesk-1") -> dict:
    """FrontDesk is opaque; id is not compared to any entity."""
    return build_user_headers(user_id, "FrontDesk")


def make_studio_manager_headers(user_id: str = "test-manager-1") -> dict:
    """StudioManager is opaque; id is not compared to any entity."""
    return build_user_headers(user_id, "StudioManager")
