"""Pre-built role headers for every role in the Country Club Membership PRD (§2.1).

ClubManager and BillingClerk are opaque operator roles: their X-User-ID is an
operator identifier never compared to any persisted entity, so the shared
constant is the canonical form for those calls.

Member is entity-backed: its X-User-ID is the id of the acting Membership, and
ownership checks compare a resource's membership_id / sponsor_membership_id to
that X-User-ID. Every ownership-gated Member call MUST therefore use the
per-instance builder make_member_headers(membership_id) with the real
Membership.id — the shared constant is a fallback only for tests that do not
exercise ownership (e.g. authentication / role-permission rejection paths).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "club_manager_headers": build_user_headers("test-manager-1", "ClubManager"),
    "billing_clerk_headers": build_user_headers("test-clerk-1", "BillingClerk"),
    # Member shared constant: fallback for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_club_manager_headers(user_id: str = "test-manager-1") -> dict:
    """ClubManager is opaque; user_id is recorded but never matched to an entity."""
    return build_user_headers(user_id, "ClubManager")


def make_billing_clerk_headers(user_id: str = "test-clerk-1") -> dict:
    """BillingClerk is opaque; user_id is recorded but never matched to an entity."""
    return build_user_headers(user_id, "BillingClerk")


def make_member_headers(user_id: str) -> dict:
    """Member (entity_backed:Membership). Pass the actual Membership.id as user_id
    whenever the call is ownership-gated (resign, payment, reservation actions,
    guest-pass register/cancel)."""
    return build_user_headers(user_id, "Member")


# Headers carrying an unrecognized role — used to exercise ERR_UNAUTHENTICATED
# (PRD §2.1: a role the system does not recognize is rejected).
def make_invalid_role_headers(user_id: str = "test-x-1", role: str = "NoSuchRole") -> dict:
    return build_user_headers(user_id, role)
