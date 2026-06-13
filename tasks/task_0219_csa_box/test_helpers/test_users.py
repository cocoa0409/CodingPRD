"""Pre-built role headers for every role in the PRD.

Roles FarmManager, DeliveryCoordinator, PlatformAdmin, Anonymous use opaque
X-User-ID values the server does not match against any entity. Member is
entity-backed: ownership checks compare X-User-ID to the resource's owning
member, so member-actor calls MUST use make_member_headers(member["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# Member ownership.
TEST_USERS = {
    "farm_manager_headers": build_user_headers("test-farm-manager-1", "FarmManager"),
    "delivery_coordinator_headers": build_user_headers("test-delivery-coordinator-1", "DeliveryCoordinator"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    # Shared Member constant: a fallback for non-ownership tests only (e.g. a
    # forbidden-role check). Never use this where ownership is enforced.
    "member_headers": build_user_headers("test-member-shared-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (subscriptions, holds, add-ons, etc.)."""
    return build_user_headers(user_id, "Member")


def make_farm_manager_headers(user_id: str = "test-farm-manager-1") -> dict:
    return build_user_headers(user_id, "FarmManager")


def make_delivery_coordinator_headers(user_id: str = "test-delivery-coordinator-1") -> dict:
    return build_user_headers(user_id, "DeliveryCoordinator")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
