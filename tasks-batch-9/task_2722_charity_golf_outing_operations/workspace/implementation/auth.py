"""Authentication and authorization — ladder tiers 1 and 2 (PRD section 2.1)."""

from flask import request

from errors import fail

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

TOURNAMENT_DIRECTOR = "TournamentDirector"
SPONSORSHIP_MANAGER = "SponsorshipManager"
CHARITY_TREASURER = "CharityTreasurer"
COURSE_OPERATIONS = "CourseOperations"
PARTICIPANT = "Participant"
BENEFICIARY = "Beneficiary"

ROLES = (
    TOURNAMENT_DIRECTOR,
    SPONSORSHIP_MANAGER,
    CHARITY_TREASURER,
    COURSE_OPERATIONS,
    PARTICIPANT,
    BENEFICIARY,
)

STAFF_ROLES = (
    TOURNAMENT_DIRECTOR,
    SPONSORSHIP_MANAGER,
    CHARITY_TREASURER,
    COURSE_OPERATIONS,
)


def authenticate():
    """Tier 1: both headers present and the role recognized."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role header must name one of the six roles.")
    return user_id, role


def auth(allowed_roles):
    """Tiers 1 and 2: authenticate, then check the role against this endpoint."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
    return user_id, role


def own_player_only(user_id, role, player_id):
    """Tier 2 ownership: a Participant acts only on their own Player row."""
    if role == PARTICIPANT and player_id != user_id:
        fail("ERR_UNAUTHORIZED", "A Participant may only act on their own player row.")
