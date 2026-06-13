"""Pre-built role headers for every role in the PRD.

NetworkAdmin and StudioManager carry `opaque` identities — the server records
X-User-ID but never compares it to a persisted entity, so a shared constant is
the canonical form for those roles. Member is `entity_backed:Member`: ownership
checks compare X-User-ID to the resource's member_id, so member-owned calls MUST
use make_member_headers(member_id) with the real Member.id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants. Safe for opaque roles (NetworkAdmin, StudioManager) and for
# Member-role tests that do not exercise ownership (e.g. 404/422 negative paths).
TEST_USERS = {
    "network_admin_headers": build_user_headers("test-network-admin-1", "NetworkAdmin"),
    "studio_manager_headers": build_user_headers("test-studio-manager-1", "StudioManager"),
    # Member shared constant: fallback for non-ownership tests only. Ownership-gated
    # calls MUST use make_member_headers(member["id"]).
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(member_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (reservations, memberships, fees
    that trace back to this member)."""
    return build_user_headers(member_id, "Member")


def make_network_admin_headers(user_id: str = "test-network-admin-1") -> dict:
    """NetworkAdmin is opaque; user_id is recorded but not ownership-checked."""
    return build_user_headers(user_id, "NetworkAdmin")


def make_studio_manager_headers(user_id: str = "test-studio-manager-1") -> dict:
    """StudioManager is opaque; user_id is recorded but not ownership-checked."""
    return build_user_headers(user_id, "StudioManager")
