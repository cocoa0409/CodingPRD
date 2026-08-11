"""Pre-built role headers for every role in the PRD (§2.1).

Member is the entity-backed role: when X-User-Role is Member, X-User-ID must be
the id of the acting Member, and ownership checks compare a resource's member_id
against it. Use make_member_headers(member_id) for any ownership-gated call.

ShopStaff / ComplianceOfficer / PlatformAdmin / Anonymous identifiers are opaque
operator credentials, never compared to entity ids, so shared constants are safe.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Entity-backed role — shared constant is a fallback for non-ownership
    # calls only (e.g. registering a member). Ownership-gated calls MUST use
    # make_member_headers(member["id"]).
    "member_headers": build_user_headers("test-member-fallback", "Member"),
    # Opaque roles — shared constants are the canonical form.
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "shop_staff_headers": build_user_headers("test-shop-staff-1", "ShopStaff"),
    "shop_staff_b_headers": build_user_headers("test-shop-staff-2", "ShopStaff"),
    "compliance_officer_headers": build_user_headers(
        "test-compliance-officer-1", "ComplianceOfficer"
    ),
    "compliance_officer_b_headers": build_user_headers(
        "test-compliance-officer-2", "ComplianceOfficer"
    ),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity-backed). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (orders, seats, subscriptions,
    special orders, own profile reads)."""
    return build_user_headers(user_id, "Member")
