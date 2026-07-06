"""Pre-built role headers for every role in the PRD.

Three of the four roles (SeasonAdmin, BoxOfficeAgent, ArtisticDirector) are
opaque operator identifiers — X-User-ID is never compared to an entity id
(PRD §2.1), so a shared constant is the canonical form for them.

The Patron role is entity-backed: X-User-ID must equal the acting Patron's id,
and ownership checks compare a resource's patron_id against it (PRD §2.1).
Tests that exercise ownership MUST therefore use make_patron_headers(patron_id)
with the real Patron id, not the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "season_admin_headers": build_user_headers("test-season-admin-1", "SeasonAdmin"),
    "box_office_agent_headers": build_user_headers("test-box-office-agent-1", "BoxOfficeAgent"),
    "artistic_director_headers": build_user_headers("test-artistic-director-1", "ArtisticDirector"),
    # Fallback only for non-ownership Patron tests (e.g. 400-on-missing-header
    # variants); ownership-gated calls must use make_patron_headers().
    "patron_headers": build_user_headers("test-patron-1", "Patron"),
}


def make_season_admin_headers(user_id="test-season-admin-1"):
    return build_user_headers(user_id, "SeasonAdmin")


def make_box_office_agent_headers(user_id="test-box-office-agent-1"):
    return build_user_headers(user_id, "BoxOfficeAgent")


def make_artistic_director_headers(user_id="test-artistic-director-1"):
    return build_user_headers(user_id, "ArtisticDirector")


def make_patron_headers(user_id: str) -> dict:
    """For the Patron role (entity_backed:Patron). Pass the actual Patron.id as
    user_id whenever the call is ownership-gated (subscriptions, tickets,
    donations, exchanges owned by that patron)."""
    return build_user_headers(user_id, "Patron")
