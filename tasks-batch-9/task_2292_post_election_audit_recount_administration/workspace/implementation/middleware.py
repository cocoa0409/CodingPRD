"""Authentication / authorization middleware (PRD section 2.1)."""

import functools

from flask import g, request

from errors import fail

ROLE_ELECTIONS_DIRECTOR = "ElectionsDirector"
ROLE_AUDIT_MANAGER = "AuditManager"
ROLE_CUSTODY_OFFICER = "CustodyOfficer"
ROLE_TALLY_TEAM_LEAD = "TallyTeamLead"
ROLE_CANVASSING_BOARD_MEMBER = "CanvassingBoardMember"
ROLE_CANDIDATE_REPRESENTATIVE = "CandidateRepresentative"
ROLE_OBSERVER = "Observer"

ALL_ROLES = (
    ROLE_ELECTIONS_DIRECTOR,
    ROLE_AUDIT_MANAGER,
    ROLE_CUSTODY_OFFICER,
    ROLE_TALLY_TEAM_LEAD,
    ROLE_CANVASSING_BOARD_MEMBER,
    ROLE_CANDIDATE_REPRESENTATIVE,
    ROLE_OBSERVER,
)

# Every role except Observer; the six operational roles that may read the
# broadly-shared collections.
SIX_ROLES = (
    ROLE_ELECTIONS_DIRECTOR,
    ROLE_AUDIT_MANAGER,
    ROLE_CUSTODY_OFFICER,
    ROLE_TALLY_TEAM_LEAD,
    ROLE_CANVASSING_BOARD_MEMBER,
    ROLE_CANDIDATE_REPRESENTATIVE,
)

ENTITY_BACKED_ROLES = (ROLE_TALLY_TEAM_LEAD, ROLE_OBSERVER)

HEADER_ROLE = "X-User-Role"
HEADER_USER_ID = "X-User-ID"


def authenticate():
    role = request.headers.get(HEADER_ROLE)
    user_id = request.headers.get(HEADER_USER_ID)
    if role is not None:
        role = role.strip()
    if user_id is not None:
        user_id = user_id.strip()
    if not role or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED")
    g.role = role
    g.user_id = user_id or None
    return role


def guard(roles):
    """Tier 1 (authentication) then tier 2 (authorization)."""
    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            role = authenticate()
            entity_backed_here = any(r in ENTITY_BACKED_ROLES for r in allowed)
            if role in ENTITY_BACKED_ROLES and entity_backed_here and not g.user_id:
                fail("ERR_UNAUTHENTICATED")
            if role not in allowed:
                fail("ERR_UNAUTHORIZED")
            if role in ENTITY_BACKED_ROLES and not g.user_id:
                fail("ERR_UNAUTHENTICATED")
            return view(*args, **kwargs)

        return wrapper

    return decorator
