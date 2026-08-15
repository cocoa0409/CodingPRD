"""Pre-built role headers for every role in the PRD (section 2.1).

LeagueOfficer is an opaque identity: X-User-ID is not tied to any persisted
entity. AgencyManager and Agent are entity-backed by Agent (X-User-ID is the
acting Agent's id); Team is entity-backed by Team; Player is entity-backed by
Client. Ownership-gated calls MUST use the per-instance builders with the
real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "league_officer_headers": build_user_headers("test-league-officer-1", "LeagueOfficer"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "agency_manager_headers": build_user_headers("test-agency-manager-1", "AgencyManager"),
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    "team_headers": build_user_headers("test-team-1", "Team"),
    "player_headers": build_user_headers("test-player-1", "Player"),
}


def make_league_officer_headers(user_id: str = "test-league-officer-1") -> dict:
    return build_user_headers(user_id, "LeagueOfficer")


def make_agency_manager_headers(agent_id: str) -> dict:
    """For AgencyManager (entity_backed:Agent). Pass the acting manager's
    Agent.id whenever the call is ownership-gated."""
    return build_user_headers(agent_id, "AgencyManager")


def make_agent_headers(agent_id: str) -> dict:
    """For Agent (entity_backed:Agent). Pass the acting Agent.id whenever the
    call is ownership-gated (submit/resubmit/withdraw/sign/exercise/grievance)."""
    return build_user_headers(agent_id, "Agent")


def make_team_headers(team_id: str) -> dict:
    """For Team (entity_backed:Team). Pass the acting Team.id whenever the call
    is ownership-gated."""
    return build_user_headers(team_id, "Team")


def make_player_headers(client_id: str) -> dict:
    """For Player (entity_backed:Client). Pass the acting Client.id whenever
    the call is ownership-gated."""
    return build_user_headers(client_id, "Player")
