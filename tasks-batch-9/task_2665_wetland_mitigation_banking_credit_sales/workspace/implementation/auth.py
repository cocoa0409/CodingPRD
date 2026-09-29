"""Authentication, role authorisation and identity resolution (PRD 2.1)."""
from flask import request

import store
from errors import ApiError

ROLE_SPONSOR = "Sponsor"
ROLE_PERMITTEE = "Permittee"
ROLE_IRT_MEMBER = "IRTMember"
ROLE_IRT_CHAIR = "IRTChair"
ROLE_PROGRAM_ADMIN = "ProgramAdmin"

ROLES = (ROLE_SPONSOR, ROLE_PERMITTEE, ROLE_IRT_MEMBER, ROLE_IRT_CHAIR, ROLE_PROGRAM_ADMIN)


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_sponsor(self):
        return self.role == ROLE_SPONSOR

    @property
    def is_permittee(self):
        return self.role == ROLE_PERMITTEE

    @property
    def is_member(self):
        return self.role == ROLE_IRT_MEMBER


def authenticate(*allowed_roles):
    """Validation priority 1 then 2: ERR_UNAUTHENTICATED then ERR_ROLE_NOT_PERMITTED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is missing or empty.")
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or empty.")
    role = str(role).strip()
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role name.")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "Role %s is not authorised for this endpoint." % role)
    return Actor(str(user_id).strip(), role)


def acting_member(actor):
    """Resolve the acting IRTMember row; unknown identity is a 404 (PRD 2.1)."""
    member = store.irt_members.get(actor.user_id)
    if member is None:
        raise ApiError("ERR_IRT_MEMBER_NOT_FOUND",
                       "The acting X-User-ID does not resolve to a review-team member.")
    return member


def check_not_recused(member):
    if member["roster_status"] == "RECUSED":
        raise ApiError("ERR_MEMBER_RECUSED", "A recused member may not perform this operation.")


def require_bank_sponsor(actor, bank):
    """Sponsor ownership check (validation priority 30)."""
    if actor.is_sponsor and bank.get("sponsor_id") != actor.user_id:
        raise ApiError("ERR_NOT_BANK_SPONSOR",
                       "The acting sponsor does not own the targeted mitigation bank.")


def require_sale_permittee(actor, permittee_id):
    """Permittee ownership check (validation priority 31)."""
    if actor.is_permittee and permittee_id != actor.user_id:
        raise ApiError("ERR_NOT_SALE_PERMITTEE",
                       "The acting permittee does not own the targeted record.")
