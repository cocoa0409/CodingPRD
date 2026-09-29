"""Authentication, endpoint authorisation, ownership scope and segregation of
duties -- bands 1 and 2 of the rejection precedence ladder (PRD 2.8)."""
from flask import request

from errors import fail

ROLES = (
    "InstitutionOfficer",
    "Borrower",
    "CertificationReviewer",
    "CreditUnderwriter",
    "CreditCommittee",
    "ComplianceAnalyst",
    "AwardAdministrator",
)

OFFICER = "InstitutionOfficer"
BORROWER = "Borrower"


class Caller(object):
    __slots__ = ("user_id", "role", "endpoint_roles")

    def __init__(self, user_id, role, endpoint_roles):
        self.user_id = user_id
        self.role = role
        self.endpoint_roles = endpoint_roles

    @property
    def is_officer(self):
        return self.role == OFFICER

    @property
    def is_borrower(self):
        return self.role == BORROWER


def authenticate(endpoint_roles):
    """Band 1 then band 2's role check."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED")
    role = str(role).strip()
    user_id = str(user_id).strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role not in endpoint_roles:
        fail("ERR_UNAUTHORIZED")
    return Caller(user_id, role, endpoint_roles)


def scope(caller, owning_institution_id):
    """Institution-ownership check.  Applies on every endpoint whose authorised
    roles include InstitutionOfficer, when the acting role is InstitutionOfficer.
    Skipped when no owning institution can be identified (the resource does not
    exist, so the later existence band reports it)."""
    if OFFICER not in caller.endpoint_roles:
        return
    if not caller.is_officer:
        return
    if owning_institution_id is None:
        return
    if caller.user_id != owning_institution_id:
        fail("ERR_INSTITUTION_SCOPE_VIOLATION")


def borrower_scope(caller, owning_borrower_id):
    """Borrower-ownership check on impact-report filing and correction."""
    if not caller.is_borrower:
        return
    if owning_borrower_id is None:
        return
    if caller.user_id != owning_borrower_id:
        fail("ERR_BORROWER_SCOPE_VIOLATION")


def segregation(caller, blocked_user_id):
    if blocked_user_id is None:
        return
    if caller.user_id == blocked_user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")
