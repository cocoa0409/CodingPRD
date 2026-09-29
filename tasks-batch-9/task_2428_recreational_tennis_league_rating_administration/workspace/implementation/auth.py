"""Authentication, role gating and ownership helpers (PRD 2.1, ranks 1-9)."""

from flask import request

from errors import ApiError
from store import db

ROLE_SECTION_ADMIN = "SectionAdmin"
ROLE_LEAGUE_COORDINATOR = "LeagueCoordinator"
ROLE_CAPTAIN = "Captain"
ROLE_PLAYER = "Player"
ROLE_COMMITTEE_MEMBER = "CommitteeMember"
ROLE_COMMITTEE_CHAIR = "CommitteeChair"

KNOWN_ROLES = (
    ROLE_SECTION_ADMIN,
    ROLE_LEAGUE_COORDINATOR,
    ROLE_CAPTAIN,
    ROLE_PLAYER,
    ROLE_COMMITTEE_MEMBER,
    ROLE_COMMITTEE_CHAIR,
)

OPAQUE_ROLES = (ROLE_SECTION_ADMIN, ROLE_LEAGUE_COORDINATOR)

ENTITY_BACKED_ROLES = (
    ROLE_CAPTAIN,
    ROLE_PLAYER,
    ROLE_COMMITTEE_MEMBER,
    ROLE_COMMITTEE_CHAIR,
)

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


class Actor(object):
    __slots__ = ("role", "user_id", "player")

    def __init__(self, role, user_id, player):
        self.role = role
        self.user_id = user_id
        self.player = player

    @property
    def player_id(self):
        return self.player["id"] if self.player else None

    def is_role(self, *roles):
        return self.role in roles


def authenticate(allowed_roles):
    """Ranks 1-5 of the precedence ladder, in order."""
    raw_role = request.headers.get("X-User-Role")
    if raw_role is None or raw_role.strip() == "":
        raise ApiError("ERR_MISSING_ROLE_HEADER")
    role = raw_role.strip()
    if role not in KNOWN_ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")

    raw_user = request.headers.get("X-User-ID")
    user_id = raw_user.strip() if raw_user is not None else None

    player = None
    if role in ENTITY_BACKED_ROLES:
        if not user_id:
            raise ApiError("ERR_MISSING_USER_ID")
        player = db.players.get(user_id)
        if player is None:
            raise ApiError("ERR_MISSING_USER_ID")

    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")

    if player is not None and request.method in WRITE_METHODS:
        if player.get("status") == "DISQUALIFIED":
            raise ApiError("ERR_ACTOR_DISQUALIFIED")

    return Actor(role, user_id, player)


def require_self(actor, player_id):
    """Rank 6 — a Player-role actor may only address its own player row."""
    if actor.role == ROLE_PLAYER and player_id != actor.user_id:
        raise ApiError("ERR_NOT_SELF")


def require_team_captain(actor, team):
    """Rank 7 — a Captain-role actor may only act for a team it captains."""
    if actor.role != ROLE_CAPTAIN:
        return
    if team is None or team.get("captain_player_id") != actor.user_id:
        raise ApiError("ERR_NOT_TEAM_CAPTAIN")


def require_match_captain(actor, match):
    """Rank 7 — a Captain must captain one of the two sides of the match."""
    if actor.role != ROLE_CAPTAIN:
        return None
    if match is None:
        raise ApiError("ERR_NOT_TEAM_CAPTAIN")
    for side in ("home_team_id", "away_team_id"):
        team = db.teams.get(match.get(side))
        if team is not None and team.get("captain_player_id") == actor.user_id:
            return team
    raise ApiError("ERR_NOT_TEAM_CAPTAIN")


def captained_team_in_league(actor, league_id):
    for team in db.teams.values():
        if team.get("league_id") == league_id and team.get("captain_player_id") == actor.user_id:
            return team
    return None
