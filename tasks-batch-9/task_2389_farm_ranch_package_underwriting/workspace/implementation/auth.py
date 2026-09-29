"""Authentication, role permission and producer scoping (PRD §2.1, §2.10)."""

from flask import g, request

from errors import ApiError

AGENT = "Agent"
UNDERWRITER = "Underwriter"
SENIOR = "SeniorUnderwriter"
LOSS_CONTROL = "LossControlSpecialist"
COMPLIANCE = "ComplianceOfficer"
ADMIN = "PlatformAdmin"

ALL_ROLES = (AGENT, UNDERWRITER, SENIOR, LOSS_CONTROL, COMPLIANCE, ADMIN)


def authenticate(*allowed_roles):
    """Priority 1 then priority 2 of the ladder; returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    role = request.headers.get("X-User-Role")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    g.user_id = user_id
    g.role = role
    return user_id, role


def is_agent():
    return getattr(g, "role", None) == AGENT


def user_id():
    return getattr(g, "user_id", None)


def guard_account(account):
    """A producer may only reach rows hanging off its own account."""
    if account is None:
        return
    if is_agent() and account.get("agent_id") != user_id():
        raise ApiError("ERR_NOT_ACCOUNT_AGENT")
