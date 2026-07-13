"""Pre-built role headers for every role in the PRD.

The `Member` role is entity-backed: its `X-User-ID` must equal the acting
member's `id` for ownership checks to pass, so ownership-gated calls use the
per-instance builder `make_member_headers(member_id)`. The other roles
(`Attorney`, `Notary`, `PlatformAdmin`) use opaque operator identifiers and the
shared constants are the canonical form.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - platform_admin / attorney / notary: opaque roles, shared constant is canonical.
#  - member: shared constant is a fallback for tests that do NOT exercise ownership
#    (e.g. a role-denial test where the request is rejected before ownership is checked).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "attorney_headers": build_user_headers("test-attorney-1", "Attorney"),
    "notary_headers": build_user_headers("test-notary-1", "Notary"),
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_attorney_headers(user_id: str = "test-attorney-1") -> dict:
    return build_user_headers(user_id, "Attorney")


def make_notary_headers(user_id: str = "test-notary-1") -> dict:
    return build_user_headers(user_id, "Notary")
