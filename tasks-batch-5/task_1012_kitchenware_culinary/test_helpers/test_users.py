"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin and StoreAssociate carry opaque operator identifiers not tied
to any entity, so their shared constants are the canonical form. Member is
entity-backed: ownership checks compare X-User-ID to the resource's member
foreign key, so ownership-gated calls MUST use make_member_headers(member_id)
with the actual Member.id — never the shared fallback below.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operator roles — shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "associate_headers": build_user_headers("test-associate-1", "StoreAssociate"),
    # Entity-backed role — shared constant is a fallback for non-ownership tests
    # (e.g. authz-only checks). Ownership-gated calls must use the builder below.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (returns create, class-
    registration create/cancel, special-order request-revision/accept/cancel,
    redeem)."""
    return build_user_headers(user_id, "Member")
