"""Pre-built role headers for every role in the PRD (Section 2.1).

Roles:
  - Parent        : X-User-ID is an opaque operator id (not an entity FK); ownership flows
                    through the Family the parent created. Shared constant is the canonical form.
  - Child         : X-User-ID is the id of the acting ChildAccount (entity_backed). Ownership-gated
                    calls MUST use make_child_headers(child_account_id) with the real child id.
  - PlatformAdmin : X-User-ID is an opaque operator id; admin is not ownership-scoped.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise child ownership.
TEST_USERS = {
    # opaque roles: shared constants are the canonical form.
    "parent_headers": build_user_headers("test-parent-1", "Parent"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # entity_backed Child: this shared constant is a fallback for non-ownership tests only
    # (e.g., 400-on-bad-payload). A real child id never equals this string, so it must NOT be
    # used for ownership-gated child calls — use make_child_headers(child["id"]) instead.
    "child_headers": build_user_headers("test-child-1", "Child"),
}


def make_parent_headers(user_id: str) -> dict:
    """Parent headers for a specific opaque operator id. Use the same id that registered
    the family (its primary_parent_id) so parent ownership resolves."""
    return build_user_headers(user_id, "Parent")


def make_child_headers(user_id: str) -> dict:
    """For Child (entity_backed:ChildAccount). Pass the actual ChildAccount.id as user_id
    whenever the call is ownership-gated (submit/resubmit/lock/authorize/orders on own resources)."""
    return build_user_headers(user_id, "Child")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """PlatformAdmin headers (opaque)."""
    return build_user_headers(user_id, "PlatformAdmin")
