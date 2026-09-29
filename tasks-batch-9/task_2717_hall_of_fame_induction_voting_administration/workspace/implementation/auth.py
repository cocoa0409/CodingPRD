"""Authentication, authorization and entity-backed identity (PRD 2.1, 2.11)."""
from flask import request

import db
from errors import fail

ROLE_ADMIN = "ElectionAdministrator"
ROLE_SCREENER = "ScreeningCommitteeMember"
ROLE_ELECTOR = "Elector"
ROLE_AUDITOR = "IndependentAuditor"
ROLE_CURATOR = "CuratorialStaff"

ROLES = (ROLE_ADMIN, ROLE_SCREENER, ROLE_ELECTOR, ROLE_AUDITOR, ROLE_CURATOR)
ALL_ROLES = ROLES

ENTITY_BACKED = (ROLE_ELECTOR, ROLE_SCREENER)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_auditor(self):
        return self.role == ROLE_AUDITOR


def caller(*allowed):
    """Band 1 then band 2: authentication before authorization."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and a recognised X-User-Role header are required.")
    if allowed and role not in allowed:
        fail("ERR_UNAUTHORIZED", "Role %s is not authorized for this operation." % role)
    return Caller(user_id, role)


def acting_elector(actor):
    """Band 4: for the entity-backed roles X-User-ID must resolve to an Elector."""
    if actor.role not in ENTITY_BACKED:
        return None
    row = db.electors.get(actor.user_id)
    if row is None:
        fail("ERR_ELECTOR_IDENTITY_UNKNOWN", "X-User-ID does not resolve to an elector.")
    return row
