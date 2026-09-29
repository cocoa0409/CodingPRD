"""Identity headers for the four roles of PRD 2.1.

The league officer's identity is opaque, so a fixed string is enough and two
distinct officers are provided for the cases where the decider must differ from
the filer. The three club and agent roles are entity backed: their ``X-User-ID``
must be the id of a real club or player record, so those headers are always
built from an id captured during setup, never from a shared constant.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers

ROLE_LEAGUE_OFFICER = "LeagueOfficer"
ROLE_TEAM_CAP_ANALYST = "TeamCapAnalyst"
ROLE_TEAM_MEDICAL_OFFICER = "TeamMedicalOfficer"
ROLE_PLAYER_AGENT = "PlayerAgent"

# Opaque league-office identities. Two of them exist so a filing decided by the
# league office can always be decided by somebody other than its filer.
LEAGUE_OFFICER_USER_ID = "league-officer-primary"
SECOND_LEAGUE_OFFICER_USER_ID = "league-officer-secondary"

TEST_USERS = {
    "league_officer": {
        "user_id": LEAGUE_OFFICER_USER_ID,
        "role": ROLE_LEAGUE_OFFICER,
    },
    "second_league_officer": {
        "user_id": SECOND_LEAGUE_OFFICER_USER_ID,
        "role": ROLE_LEAGUE_OFFICER,
    },
}

LEAGUE_OFFICER_HEADERS: Headers = build_user_headers(
    LEAGUE_OFFICER_USER_ID, ROLE_LEAGUE_OFFICER
)
SECOND_LEAGUE_OFFICER_HEADERS: Headers = build_user_headers(
    SECOND_LEAGUE_OFFICER_USER_ID, ROLE_LEAGUE_OFFICER
)


def make_league_officer_headers(user_id: str = LEAGUE_OFFICER_USER_ID) -> Headers:
    """Headers for the league transactions office; the id is opaque."""
    return build_user_headers(user_id, ROLE_LEAGUE_OFFICER)


def make_cap_analyst_headers(team_id: str) -> Headers:
    """Headers for a club's cap analyst; the id must be that club's id."""
    return build_user_headers(team_id, ROLE_TEAM_CAP_ANALYST)


def make_medical_officer_headers(team_id: str) -> Headers:
    """Headers for a club's medical officer; the id must be that club's id."""
    return build_user_headers(team_id, ROLE_TEAM_MEDICAL_OFFICER)


def make_agent_headers(player_id: str) -> Headers:
    """Headers for a player's agent; the id must be that player's id."""
    return build_user_headers(player_id, ROLE_PLAYER_AGENT)


def make_headers(user_id: str, role: str) -> Headers:
    """Arbitrary identity pair, for the authorisation and scope cases."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str) -> Headers:
    """An identity that supplies only the user id, leaving the role absent."""
    return {"X-User-ID": user_id}


def headers_without_user_id(role: str) -> Headers:
    """An identity that supplies only the role, leaving the user id absent."""
    return {"X-User-Role": role}


def headers_with_blank_role(user_id: str) -> Headers:
    """An identity whose role header is present but blank."""
    return {"X-User-ID": user_id, "X-User-Role": ""}


NO_HEADERS: Headers = {}
