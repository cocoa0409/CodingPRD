"""Pre-built role headers for every role in the PRD (§2.1).

The PRD recognizes exactly four roles: BarnManager, Owner, Instructor,
ServiceProvider. Of these, only Owner is entity-backed — its X-User-ID is the
acting Owner's id, and ownership checks compare that id against the resource's
resolved owner. BarnManager, Instructor and ServiceProvider are opaque operator
identities the server never compares against any entity id.

Therefore the Owner shared constant below is only a fallback for tests that do
NOT exercise ownership (e.g. a 401/403 denial that never reaches the ownership
check). Any ownership-gated Owner call MUST use make_owner_headers(owner_id)
with the real Owner.id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — canonical for the three opaque roles; the Owner entry is a
# non-ownership fallback only.
TEST_USERS = {
    "barn_manager_headers": build_user_headers("test-barn-manager-1", "BarnManager"),
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "service_provider_headers": build_user_headers(
        "test-service-provider-1", "ServiceProvider"
    ),
}


def make_owner_headers(owner_id: str) -> dict:
    """For the entity-backed Owner role. Pass the actual Owner.id as owner_id
    whenever the call is ownership-gated (signing/creating waivers, acting on own
    horses, lessons, requests, withdrawals)."""
    return build_user_headers(owner_id, "Owner")
