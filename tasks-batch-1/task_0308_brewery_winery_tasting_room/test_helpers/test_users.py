"""Pre-built role headers for every role in the PRD (Section 2.1).

The four staff roles (ComplianceOfficer, CellarManager, ClubManager,
TastingRoomStaff) carry an opaque identity: X-User-ID is an operator token
never compared to any entity id, so the shared constants are canonical for them.

The Member role is entity_backed: X-User-ID must equal the acting Member.id.
Ownership-gated Member reads MUST use make_member_headers(member["id"]).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque staff roles — shared constants are the canonical form.
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "cellar_manager_headers": build_user_headers("test-cellar-1", "CellarManager"),
    "club_manager_headers": build_user_headers("test-club-1", "ClubManager"),
    "tasting_room_staff_headers": build_user_headers("test-tasting-1", "TastingRoomStaff"),
    # entity_backed Member role: shared constant is a fallback for non-ownership
    # tests only (e.g. ERR_NOT_RESOURCE_OWNER negative checks). Ownership-gated
    # reads must use make_member_headers(member_id).
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the read is ownership-gated (own member/memberships/shipments)."""
    return build_user_headers(user_id, "Member")
