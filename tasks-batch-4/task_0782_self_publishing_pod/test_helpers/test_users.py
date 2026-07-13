"""Pre-built role headers for every role in the PRD.

  - Reviewer and PlatformAdmin are opaque operator identities (PRD 2.1): the
    server never compares their X-User-ID to any entity id, so a shared
    constant is the canonical form.
  - Publisher is entity_backed:Publisher — its X-User-ID must equal the acting
    Publisher entity's id for ownership-gated mutations. The shared
    "publisher_headers" constant is a fallback only for tests that do NOT
    exercise ownership (e.g. a request rejected before the ownership check).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "reviewer_headers": build_user_headers("reviewer-1", "Reviewer"),
    "publisher_headers": build_user_headers("test-publisher-1", "Publisher"),
}


def make_publisher_headers(publisher_id: str) -> dict:
    """For Publisher (entity_backed:Publisher). Pass the actual Publisher.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(publisher_id, "Publisher")


def make_reviewer_headers(user_id: str = "reviewer-1") -> dict:
    return build_user_headers(user_id, "Reviewer")


def make_admin_headers(user_id: str = "admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
