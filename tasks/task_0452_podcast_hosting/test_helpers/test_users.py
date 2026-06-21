"""Pre-built role headers for every role in the PRD (Podcast Hosting & Monetization API).

PRD §2.1: Publisher, Advertiser, and Listener are entity-backed — X-User-ID is the id
of the acting persisted actor and is used for ownership checks. PlatformAdmin is opaque —
X-User-ID is an operator identifier never compared to any entity id.

Tests/fixtures whose success depends on the caller OWNING the subject resource MUST use the
per-instance builders below (make_publisher_headers / make_advertiser_headers /
make_listener_headers) with the actual persisted actor's id. The shared TEST_USERS constants
are only safe for opaque PlatformAdmin calls and for non-ownership tests (e.g. 401/403-role
checks where the call is refused before ownership is examined).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque PlatformAdmin role and for tests that do not
# exercise ownership (forbidden-role / unauthenticated checks).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "publisher_headers": build_user_headers("test-publisher-1", "Publisher"),
    "advertiser_headers": build_user_headers("test-advertiser-1", "Advertiser"),
    "listener_headers": build_user_headers("test-listener-1", "Listener"),
}


# Per-instance builders — mandatory for the entity-backed roles. Pass the actual actor id.
def make_publisher_headers(publisher_id: str) -> dict:
    """For the Publisher role (entity_backed:Publisher). Pass the acting Publisher.id."""
    return build_user_headers(publisher_id, "Publisher")


def make_advertiser_headers(advertiser_id: str) -> dict:
    """For the Advertiser role (entity_backed:Advertiser). Pass the acting Advertiser.id."""
    return build_user_headers(advertiser_id, "Advertiser")


def make_listener_headers(listener_id: str) -> dict:
    """For the Listener role (entity_backed:Listener). Pass the acting Listener.id."""
    return build_user_headers(listener_id, "Listener")
