"""Authentication and role authorisation (PRD section 2.1, ladder rungs 1-2)."""

from flask import request

from errors import fail

SYSTEM_ADMIN = "SystemAdmin"
AGENCY_BUDGET_OFFICER = "AgencyBudgetOfficer"
BUDGET_ANALYST = "BudgetAnalyst"
BUDGET_DIRECTOR = "BudgetDirector"
LEGISLATIVE_FISCAL_OFFICER = "LegislativeFiscalOfficer"
STATE_CONTROLLER = "StateController"

ROLES = (
    SYSTEM_ADMIN,
    AGENCY_BUDGET_OFFICER,
    BUDGET_ANALYST,
    BUDGET_DIRECTOR,
    LEGISLATIVE_FISCAL_OFFICER,
    STATE_CONTROLLER,
)

ANY_ROLE = ROLES


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_agency_officer(self):
        return self.role == AGENCY_BUDGET_OFFICER


def authenticate(allowed_roles):
    """Rung 1 then rung 2 of the global validation ladder."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and a valid X-User-Role header are required.")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not call this endpoint." % role)
    return Actor(user_id, role)


def require_agency_scope(actor, agency_id):
    """Rung 5: an AgencyBudgetOfficer may only touch its own agency's rows."""
    if actor.is_agency_officer and actor.user_id != agency_id:
        fail(
            "ERR_AGENCY_SCOPE_VIOLATION",
            "Acting officer does not belong to the target agency.",
        )
