"""Auth header extraction, role checks, and entity-backed scoping (PRD 2.1, validation order 1-4)."""
from flask import request

from db import db
from errors import (
    ApiError,
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_ARTIST_ACCESS_DENIED,
    ERR_TEAM_MEMBER_INACTIVE,
)

ALL_ROLES = {"FirmAdmin", "Agent", "BusinessManager", "Publicist", "Artist", "Auditor"}
TEAM_ROLES = {"Agent": "AGENT", "BusinessManager": "BUSINESS_MANAGER", "Publicist": "PUBLICIST"}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role
        self.team_member = None  # resolved TeamMember for team-backed roles
        self.artist_scope_id = None  # artist_id this caller is scoped to (entity-backed roles)


def get_caller() -> Caller:
    """Priority 1: header presence."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise_error(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-ID and X-User-Role headers must both be present and non-empty")
    return Caller(user_id, role)


def check_role_allowed(caller: Caller, allowed_roles):
    """Priority 2: role membership in the endpoint's declared role list."""
    if caller.role not in allowed_roles:
        raise_error(ERR_FORBIDDEN_FOR_ROLE,
                    f"role {caller.role} is not authorized for this endpoint")


def resolve_entity_backed(caller: Caller):
    """Resolve team-backed identity (Agent/BusinessManager/Publicist) or Artist identity.

    Note: resolution failure for team roles means we cannot establish artist scope.
    Per validation order, scoping (priority 3) is checked before team-member status
    (priority 4). An unresolvable team member id cannot match the target artist chain,
    so scope checks will deny; for unscoped requests we deny access.
    """
    if caller.role in TEAM_ROLES:
        tm = db["team_members"].get(caller.user_id)
        if tm is not None and tm["member_role"] == TEAM_ROLES[caller.role]:
            caller.team_member = tm
            caller.artist_scope_id = tm["artist_id"]
    elif caller.role == "Artist":
        caller.artist_scope_id = caller.user_id
    # FirmAdmin / Auditor: opaque, no scoping


def check_artist_scope(caller: Caller, artist_id):
    """Priority 3: entity-backed callers may only touch their own artist's resources.

    artist_id=None means the target's artist chain cannot be determined yet
    (e.g. creation of an artist, clock, artist collection list) — those endpoints
    skip this check.
    """
    if artist_id is None:
        return
    if caller.role in TEAM_ROLES or caller.role == "Artist":
        if caller.artist_scope_id is None or caller.artist_scope_id != artist_id:
            raise_error(ERR_ARTIST_ACCESS_DENIED,
                        "caller's artist scope does not match the target resource's artist")


def check_team_active(caller: Caller):
    """Priority 4: entity-backed team callers must be ACTIVE."""
    if caller.role in TEAM_ROLES:
        if caller.team_member is None:
            # Unknown team member: cannot be an ACTIVE member of any team
            raise_error(ERR_ARTIST_ACCESS_DENIED,
                        "X-User-ID does not resolve to a team member with matching role")
        if caller.team_member["status"] != "ACTIVE":
            raise_error(ERR_TEAM_MEMBER_INACTIVE,
                        "team member is SUSPENDED or ENDED")


def authorized(allowed_roles, artist_id=None) -> Caller:
    """Run auth priorities 1-4 for a request.

    Order: header presence -> role membership -> scope resolution + check -> team status.
    """
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    resolve_entity_backed(caller)
    check_artist_scope(caller, artist_id)
    check_team_active(caller)
    return caller
