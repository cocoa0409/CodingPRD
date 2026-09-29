"""Authentication and authorization (PRD section 2.1).

Every request carries two headers: X-User-ID (the caller's opaque identity, which
for a GroupLeader *is* the id of their GroupLeaderAgreement) and X-User-Role.
Authentication runs before authorization, and both run before path resolution,
body parsing and every business rule.
"""

from flask import request

from db import db
from errors import err

ROLE_PROGRAM_MANAGER = "ProgramManager"
ROLE_RISK_OFFICER = "RiskOfficer"
ROLE_AIR_DESK_AGENT = "AirDeskAgent"
ROLE_LAND_CONTRACTOR = "LandContractor"
ROLE_FINANCE_CONTROLLER = "FinanceController"
ROLE_PROTECTION_ADMINISTRATOR = "ProtectionAdministrator"
ROLE_GROUP_LEADER = "GroupLeader"

OPERATOR_ROLES = (
    ROLE_PROGRAM_MANAGER,
    ROLE_RISK_OFFICER,
    ROLE_AIR_DESK_AGENT,
    ROLE_LAND_CONTRACTOR,
    ROLE_FINANCE_CONTROLLER,
    ROLE_PROTECTION_ADMINISTRATOR,
)

ALL_ROLES = OPERATOR_ROLES + (ROLE_GROUP_LEADER,)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_group_leader(self):
        return self.role == ROLE_GROUP_LEADER


def _header(*names):
    for name in names:
        value = request.headers.get(name)
        if value is not None:
            return value
    return None


def authenticate():
    """Stage 1 of the ladder: recognise the role, else ERR_UNAUTHENTICATED."""
    role = _header("X-User-Role", "X-Role")
    user_id = _header("X-User-ID", "X-User-Id") or ""
    if role is None or role.strip() == "":
        err("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = role.strip()
    if role not in ALL_ROLES:
        err("ERR_UNAUTHENTICATED", "Unrecognised role '%s'." % role)
    return Caller(user_id.strip(), role)


def authorize(allowed_roles):
    """Stages 1 and 2 of the ladder.

    A GroupLeader is additionally required to present an X-User-ID that resolves
    to a stored GroupLeaderAgreement; an unknown id is ERR_UNAUTHORIZED.
    """
    caller = authenticate()
    if caller.role not in allowed_roles:
        err("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % caller.role)
    if caller.is_group_leader:
        if not caller.user_id or caller.user_id not in db.agreements:
            err("ERR_UNAUTHORIZED", "X-User-ID does not identify a group leader agreement.")
    return caller
