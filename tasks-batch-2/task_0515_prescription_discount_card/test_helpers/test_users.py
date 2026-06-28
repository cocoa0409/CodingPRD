"""Pre-built role headers for every role in the PRD (§2.1).

Member is the only entity-backed role: its X-User-ID must equal the acting
Member entity's id for ownership-gated calls. The other four roles are opaque
operator identifiers the server never compares against any entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for Member tests that do NOT
# exercise ownership (e.g. 400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "member_headers": build_user_headers("test-member-1", "Member"),
    "pharmacy_operator_headers": build_user_headers("test-operator-1", "PharmacyOperator"),
    "copay_sponsor_headers": build_user_headers("test-sponsor-1", "CopayCardSponsor"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (comparisons run, discount-card void,
    gold revoke, mail-orders, copay-links, telehealth, insurance-estimate)."""
    return build_user_headers(user_id, "Member")


def make_role_headers(role: str, user_id: str) -> dict:
    """Generic builder for arbitrary role/id pairs (used for unauthenticated and
    cross-role negative tests)."""
    return build_user_headers(user_id, role)
