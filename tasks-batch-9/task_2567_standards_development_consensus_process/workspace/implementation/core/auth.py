"""Authentication and role admission (PRD 2.1, ladder precedence 10 and 20)."""

from flask import g, request

from .errors import fail
from .store import db

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

PROPOSER = "Proposer"
COMMITTEE_MEMBER = "CommitteeMember"
COMMITTEE_CHAIR = "CommitteeChair"
PUBLIC_COMMENTER = "PublicCommenter"
STANDARDS_STAFF = "StandardsStaff"
APPEALS_BOARD = "AppealsBoard"

ROLES = (
    PROPOSER,
    COMMITTEE_MEMBER,
    COMMITTEE_CHAIR,
    PUBLIC_COMMENTER,
    STANDARDS_STAFF,
    APPEALS_BOARD,
)

PARTICIPANT_ROLES = (PROPOSER, COMMITTEE_MEMBER, COMMITTEE_CHAIR, PUBLIC_COMMENTER)
OPAQUE_ROLES = (STANDARDS_STAFF, APPEALS_BOARD)

# Every collection is readable by every role.
READ_ROLES = ROLES


def authenticate(allowed_roles):
    """Precedence 10 then 20: both decided from the headers alone, before any
    path segment is resolved and before any resource is loaded."""
    raw_id = request.headers.get(HEADER_USER_ID)
    raw_role = request.headers.get(HEADER_USER_ROLE)
    if raw_id is None or raw_id.strip() == "" or raw_role is None or raw_role.strip() == "":
        fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role are required.")
    user_id = raw_id.strip()
    role = raw_role.strip()
    if role not in ROLES or role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role '%s' may not perform this operation." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def caller_id():
    return g.user_id


def caller_role():
    return g.role


def caller_is_participant_backed():
    return g.role in PARTICIPANT_ROLES


def require_actor_identity(*submitted_ids):
    """Precedence 64. For the four participant-backed roles the X-User-ID must
    resolve to a stored Participant and every submitter-identity field in the
    body must equal it. Opaque operator ids are never compared to entity ids."""
    if not caller_is_participant_backed():
        return
    if g.user_id not in db.participants:
        fail("ERR_ACTOR_IDENTITY_MISMATCH",
             "X-User-ID does not resolve to a known participant.")
    for submitted in submitted_ids:
        if submitted is not None and submitted != g.user_id:
            fail("ERR_ACTOR_IDENTITY_MISMATCH",
                 "The submitted participant identifier does not match X-User-ID.")


def require_committee_chair(committee):
    """Precedence 60."""
    if committee is None or g.user_id != committee.get("chair_participant_id"):
        fail("ERR_NOT_COMMITTEE_CHAIR",
             "Only the governing committee's chair may perform this operation.")


def require_vote_owner(membership):
    """Precedence 62."""
    if membership is None or g.user_id != membership.get("participant_id"):
        fail("ERR_NOT_VOTE_OWNER", "Only the casting participant may act on this vote.")
