"""Pre-built role headers for every role in the PRD (§2.1).

Member is identity-bound: its X-User-ID must equal the acting Member entity's id
whenever the operation is ownership-gated. Use make_member_headers(member_id) for
those calls. FrontDeskStaff, SalonManager, and BillingSystem are opaque operator
identifiers never compared to any entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — opaque operator roles use these directly. The Member entry
# is a fallback only for tests that do NOT exercise ownership.
TEST_USERS = {
    "member_headers": build_user_headers("test-member-1", "Member"),
    "front_desk_headers": build_user_headers("test-frontdesk-1", "FrontDeskStaff"),
    "salon_manager_headers": build_user_headers("test-manager-1", "SalonManager"),
    "billing_system_headers": build_user_headers("test-billing-1", "BillingSystem"),
}


def make_member_headers(member_id: str) -> dict:
    """For the Member role (identity_bound:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (freeze/unfreeze/upgrade/cancel,
    booking a session, placing a retail order)."""
    return build_user_headers(member_id, "Member")


def make_front_desk_headers(user_id: str = "test-frontdesk-1") -> dict:
    return build_user_headers(user_id, "FrontDeskStaff")


def make_salon_manager_headers(user_id: str = "test-manager-1") -> dict:
    return build_user_headers(user_id, "SalonManager")


def make_billing_system_headers(user_id: str = "test-billing-1") -> dict:
    return build_user_headers(user_id, "BillingSystem")
