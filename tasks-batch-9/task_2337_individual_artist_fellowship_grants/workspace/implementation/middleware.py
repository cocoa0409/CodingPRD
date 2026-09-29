"""Authentication / authorization (PRD sections 2.1 and 2.10 steps 1-2)."""

from flask import request

import db
from errors import ApiError

PROGRAM_OFFICER = "ProgramOfficer"
ARTIST = "Artist"
PANELIST = "Panelist"
BOARD = "CouncilBoardMember"
APPEALS = "AppealsOfficer"
FISCAL = "FiscalOfficer"

ROLES = (PROGRAM_OFFICER, ARTIST, PANELIST, BOARD, APPEALS, FISCAL)

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


def caller():
    """Step 1 of the rejection ladder: both headers present, role recognised."""
    user_id = request.headers.get(USER_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if user_id is None or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = role.strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unrecognised X-User-Role value.")
    return user_id.strip(), role


def authorize(allowed, entity_backed=False):
    """Steps 1-2: authenticate, check the role, resolve entity-backed callers.

    Returns (user_id, role).
    """
    user_id, role = caller()
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    if entity_backed:
        if role == ARTIST and db.get("artists", user_id) is None:
            raise ApiError("ERR_UNAUTHORIZED", "X-User-ID does not resolve to an artist.")
        if role == PANELIST and db.get("panelists", user_id) is None:
            raise ApiError("ERR_UNAUTHORIZED", "X-User-ID does not resolve to a panelist.")
    return user_id, role
