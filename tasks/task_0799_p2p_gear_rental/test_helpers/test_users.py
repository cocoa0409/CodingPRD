"""Pre-built role headers for every role in the PRD.

Renter and Owner are entity-backed (X-User-ID is the acting User.id); ownership
checks compare the target resource's owning FK to X-User-ID. Any ownership-gated
call MUST use make_renter_headers(user_id) / make_owner_headers(user_id) with the
actual User id. Platform is opaque; its X-User-ID is never compared to an entity id.
Anonymous carries no auth headers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise ownership.
TEST_USERS = {
    "platform_headers": build_user_headers("platform-operator-1", "Platform"),
    # Fallback constants for non-ownership tests only (e.g. RBAC-denied, 404).
    "renter_headers": build_user_headers("test-renter-1", "Renter"),
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
}

# Anonymous / unauthenticated: no auth headers at all.
ANONYMOUS_HEADERS: dict = {}


def make_renter_headers(user_id: str) -> dict:
    """For Renter (entity_backed:User). Pass the acting User.id whenever the call
    is ownership-gated (e.g. cancel/extend on a booking whose renter_id is user_id)."""
    return build_user_headers(user_id, "Renter")


def make_owner_headers(user_id: str) -> dict:
    """For Owner (entity_backed:User). Pass the acting User.id whenever the call is
    ownership-gated (e.g. approve/pickup/return on a booking whose listing.owner_id
    is user_id, or a handoff whose owner_id is user_id)."""
    return build_user_headers(user_id, "Owner")


def platform_headers() -> dict:
    return TEST_USERS["platform_headers"]
