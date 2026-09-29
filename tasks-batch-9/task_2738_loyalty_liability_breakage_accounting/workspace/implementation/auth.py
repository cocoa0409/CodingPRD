"""Authentication, role authorisation and ownership (PRD §2.1, ladder rungs 1-4)."""
from flask import g, request

from errors import ApiError

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_LOYALTY_ACCOUNTANT = "LoyaltyAccountant"
ROLE_CONTROLLER = "Controller"
ROLE_PARTNER_OPERATOR = "PartnerOperator"
ROLE_MEMBER = "Member"

ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_LOYALTY_ACCOUNTANT,
    ROLE_CONTROLLER,
    ROLE_PARTNER_OPERATOR,
    ROLE_MEMBER,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authorize(*allowed_roles):
    """Ladder rungs 1-3. Returns the acting (user_id, role)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS", 401)
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", 401)
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", 403)
    g.user_id = user_id
    g.role = role
    return user_id, role


def not_owner():
    return ApiError("ERR_NOT_RESOURCE_OWNER", 403)


def require_member_owns(user_id, role, owner_member_id):
    """Ladder rung 4 for the Member role (entity-backed identity = Member.id)."""
    if role == ROLE_MEMBER and owner_member_id != user_id:
        raise not_owner()


def require_operator_owns(user_id, role, agreement_id):
    """Ladder rung 4 for PartnerOperator (identity = PartnerAgreement.id)."""
    if role == ROLE_PARTNER_OPERATOR and agreement_id != user_id:
        raise not_owner()
