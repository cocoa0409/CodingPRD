"""Pre-built role headers for every role in the PRD.

Three roles (Anonymous, StudioStaff, StudioManager) carry an opaque identity:
their X-User-ID is an operator id never compared to any entity. LoyaltyMember is
identity-backed: ownership checks compare a resource's owning member_id to
X-User-ID, so member-scoped calls MUST use make_member_headers(member["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque roles are canonical here; the LoyaltyMember entry is
# a fallback only for tests that do NOT exercise ownership.
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "staff_headers": build_user_headers("staff-1", "StudioStaff"),
    "manager_headers": build_user_headers("manager-1", "StudioManager"),
    # Fallback only — see make_member_headers for ownership-gated calls.
    "member_headers": build_user_headers("member-fallback-1", "LoyaltyMember"),
}


def make_member_headers(user_id: str) -> dict:
    """For LoyaltyMember (identity-backed). Pass the actual LoyaltyMember.id as
    user_id whenever the call is ownership-gated (own visits/enrollments/ledger/
    bookings/points-preview)."""
    return build_user_headers(user_id, "LoyaltyMember")
