"""Caller identity and role authorization (PRD 2.1, global order steps 1-3)."""

from flask import request

from errors import ERR_ROLE_NOT_PERMITTED, ERR_UNAUTHENTICATED, fail

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_ROUTE_MANAGER = "RouteManager"
ROLE_CONTRACT_NEGOTIATOR = "ContractNegotiator"
ROLE_GENERAL_MANAGER = "GeneralManager"
ROLE_LOT_BOSS = "LotBoss"
ROLE_SAFETY_OFFICER = "SafetyOfficer"
ROLE_COMPLIANCE_CLERK = "ComplianceClerk"
ROLE_JURISDICTION_OFFICER = "JurisdictionOfficer"
ROLE_TICKETING_AUDITOR = "TicketingAuditor"
ROLE_CREW_CHIEF = "CrewChief"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_ROUTE_MANAGER,
    ROLE_CONTRACT_NEGOTIATOR,
    ROLE_GENERAL_MANAGER,
    ROLE_LOT_BOSS,
    ROLE_SAFETY_OFFICER,
    ROLE_COMPLIANCE_CLERK,
    ROLE_JURISDICTION_OFFICER,
    ROLE_TICKETING_AUDITOR,
    ROLE_CREW_CHIEF,
)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_role(*allowed):
    """Step 1 (401) then step 2 (403)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not role or role not in ALL_ROLES:
        fail(ERR_UNAUTHENTICATED,
             "X-User-ID and a recognized X-User-Role header are required.")
    if role not in allowed:
        fail(ERR_ROLE_NOT_PERMITTED,
             "Role %s may not perform this operation." % role)
    return Caller(user_id, role)
