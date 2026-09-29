"""Identity, roles and actor scope (PRD 2.1 and validation ladder rules 1-6)."""
import functools

from flask import request

from errors import fail
from store import db

LEAGUE_OFFICER = "LeagueOfficer"
TEAM_CAP_ANALYST = "TeamCapAnalyst"
TEAM_MEDICAL_OFFICER = "TeamMedicalOfficer"
PLAYER_AGENT = "PlayerAgent"

ALL_ROLES = (LEAGUE_OFFICER, TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER, PLAYER_AGENT)
TEAM_BACKED_ROLES = (TEAM_CAP_ANALYST, TEAM_MEDICAL_OFFICER)

ID_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role
        self.team = db.teams.get(user_id) if role in TEAM_BACKED_ROLES else None
        self.player = db.players.get(user_id) if role == PLAYER_AGENT else None

    @property
    def team_id(self):
        return self.team["id"] if self.team else None

    @property
    def player_id(self):
        return self.player["id"] if self.player else None


def authenticate(allowed_roles):
    raw_id = request.headers.get(ID_HEADER)
    raw_role = request.headers.get(ROLE_HEADER)
    # Rule 1: both identity headers present and non-blank.
    if raw_id is None or not str(raw_id).strip():
        fail("ERR_UNAUTHENTICATED", "missing identity header")
    if raw_role is None or not str(raw_role).strip():
        fail("ERR_UNAUTHENTICATED", "missing role header")
    user_id = str(raw_id).strip()
    role = str(raw_role).strip()
    # Rule 2: the role names one of the four declared roles.
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "unknown role")
    # Rule 3: the role is authorised for this endpoint.
    if allowed_roles and role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role not permitted for this operation")
    actor = Actor(user_id, role)
    # Rule 4: entity-backed identities must resolve to a live record.
    if role in TEAM_BACKED_ROLES and actor.team is None:
        fail("ERR_UNAUTHORIZED", "unknown club identity")
    if role == PLAYER_AGENT and actor.player is None:
        fail("ERR_UNAUTHORIZED", "unknown player identity")
    return actor


def endpoint(*allowed_roles):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            actor = authenticate(allowed_roles)
            return fn(actor, **kwargs)
        return wrapper
    return decorator


def require_team_scope(actor, team_id):
    """Rule 5: the acting club must be the club the resource belongs to."""
    if actor.role in TEAM_BACKED_ROLES and actor.user_id != team_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION", "resource belongs to another club")


def require_player_scope(actor, player_id):
    if actor.role == PLAYER_AGENT and actor.user_id != player_id:
        fail("ERR_ACTOR_SCOPE_VIOLATION", "resource belongs to another player")


def require_segregation(actor, filed_by_user_id):
    """Rule 6: the deciding officer may not be the filer."""
    if filed_by_user_id is not None and actor.user_id == filed_by_user_id:
        fail("ERR_SEGREGATION_OF_DUTIES", "decider must differ from filer")
