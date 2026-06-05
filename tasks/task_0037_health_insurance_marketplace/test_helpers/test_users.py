"""Pre-built role headers for every role in the PRD.

All three roles use an opaque X-User-ID. For Applicant, the X-User-ID is recorded
as the owning household's applicant_user_id, so ownership-gated calls must use the
SAME X-User-ID that created the household. Use make_applicant_headers(user_id) to
thread a specific applicant id through a fixture.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque-role tests and tests that don't exercise ownership.
TEST_USERS = {
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
    "navigator_headers": build_user_headers("test-navigator-1", "Navigator"),
    "admin_headers": build_user_headers("test-admin-1", "MarketplaceAdmin"),
}


def make_applicant_headers(user_id: str) -> dict:
    """Headers for an Applicant identified by `user_id`. Pass the same user_id that
    created the household for all ownership-gated calls on that household subtree."""
    return build_user_headers(user_id, "Applicant")


def make_navigator_headers(user_id: str = "test-navigator-1") -> dict:
    return build_user_headers(user_id, "Navigator")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "MarketplaceAdmin")
