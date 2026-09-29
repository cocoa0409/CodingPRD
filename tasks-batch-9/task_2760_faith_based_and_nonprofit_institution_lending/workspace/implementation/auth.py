"""Authentication, RBAC and the institution-scope check (PRD section 2.1)."""

from flask import request

import store
from errors import ApiError

PLATFORM_ADMIN = "PlatformAdmin"
INSTITUTION_REP = "InstitutionRepresentative"
GOVERNANCE_OFFICER = "GovernanceOfficer"
CREDIT_ANALYST = "CreditAnalyst"
COMMITTEE_MEMBER = "CreditCommitteeMember"
LOAN_SERVICER = "LoanServicer"

ROLES = (
    PLATFORM_ADMIN,
    INSTITUTION_REP,
    GOVERNANCE_OFFICER,
    CREDIT_ANALYST,
    COMMITTEE_MEMBER,
    LOAN_SERVICER,
)

READ_ALL = (PLATFORM_ADMIN, CREDIT_ANALYST, COMMITTEE_MEMBER, LOAN_SERVICER,
            INSTITUTION_REP)


class Ctx(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_rep(self):
        return self.role == INSTITUTION_REP


def authenticate(allowed_roles):
    """Ladder rungs 1 and 2: headers present + role authorised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip() or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return Ctx(str(user_id), role)


def scope(ctx, institution_id):
    """Ladder rung 3.  A representative acts only within its own institution."""
    if not ctx.is_rep:
        return
    if institution_id is None or not isinstance(institution_id, str):
        return
    if institution_id != ctx.user_id:
        raise ApiError("ERR_INSTITUTION_SCOPE_VIOLATION")


# ---------------------------------------------------------------------------
# transitive owner resolution
# ---------------------------------------------------------------------------


def owner_of_campaign(campaign):
    return campaign.get("institution_id") if campaign else None


def owner_of_pledge(pledge):
    if not pledge:
        return None
    campaign = store.pledge_campaigns.get(pledge.get("pledge_campaign_id"))
    return owner_of_campaign(campaign)


def owner_of_application(application):
    return application.get("institution_id") if application else None


def owner_of_loan(loan):
    if not loan:
        return None
    application = store.loan_applications.get(loan.get("loan_application_id"))
    return owner_of_application(application)


def owner_of_draw(draw):
    if not draw:
        return None
    return owner_of_loan(store.loans.get(draw.get("loan_id")))


def owner_of_covenant(covenant):
    if not covenant:
        return None
    return owner_of_loan(store.loans.get(covenant.get("loan_id")))


def owner_of_workout(plan):
    if not plan:
        return None
    return owner_of_loan(store.loans.get(plan.get("loan_id")))
