"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles (PlatformAdmin), and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin", "PlatformAdmin"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "client_admin_headers": build_user_headers("test-client-admin-fallback", "ClientAdmin"),
    "location_manager_headers": build_user_headers("test-location-manager-fallback", "LocationManager"),
}


# Per-instance builders — required for every entity_backed role.
def make_client_admin_headers(client_id: str) -> dict:
    """For ClientAdmin (entity_backed:Client). Pass the actual Client.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(client_id, "ClientAdmin")


def make_location_manager_headers(location_id: str) -> dict:
    """For LocationManager (entity_backed:Location). Pass the actual Location.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(location_id, "LocationManager")


def make_platform_admin_headers(user_id: str = "test-platform-admin") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
