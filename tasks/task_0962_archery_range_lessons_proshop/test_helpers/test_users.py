"""Pre-built role headers for every role in the PRD (§2.1).

`Member` and `Coach` are entity-backed roles: whenever a call is
ownership-gated, build headers with the actual entity's id via
make_member_headers(entity_id) / make_coach_headers(entity_id).
The shared constants for those two roles are fallbacks for tests that do
not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles: shared constant is the canonical form.
    "anonymous_headers": build_user_headers("anon-operator-1", "Anonymous"),
    "range_officer_headers": build_user_headers("range-officer-1", "RangeOfficer"),
    "shop_clerk_headers": build_user_headers("shop-clerk-1", "ShopClerk"),
    "league_director_headers": build_user_headers(
        "league-director-1", "LeagueDirector"
    ),
    "admin_headers": build_user_headers("admin-1", "Admin"),
    # Entity-backed roles: fallback for non-ownership tests only.
    "member_headers": build_user_headers("member-fallback-1", "Member"),
    "coach_headers": build_user_headers("coach-fallback-1", "Coach"),
}


def make_member_headers(user_id: str) -> dict:
    """For the entity-backed Member role. Pass the acting Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Member")


def make_coach_headers(user_id: str) -> dict:
    """For the entity-backed Coach role. Pass the acting Coach.id as user_id
    whenever the call is ownership-gated (lesson actions)."""
    return build_user_headers(user_id, "Coach")
