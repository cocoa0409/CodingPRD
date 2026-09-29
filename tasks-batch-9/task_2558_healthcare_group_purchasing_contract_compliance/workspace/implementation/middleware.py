"""Authentication, role admission and member scoping (PRD section 2.1)."""

from flask import request

from errors import ApiError

CONTRACT_MANAGER = "ContractManager"
CLINICAL_REVIEWER = "ClinicalReviewer"
COMPLIANCE_ANALYST = "ComplianceAnalyst"
MEMBER_MATERIALS_MANAGER = "MemberMaterialsManager"
DISTRIBUTOR_AGENT = "DistributorAgent"
FINANCE_ADMINISTRATOR = "FinanceAdministrator"

ALL_ROLES = (
    CONTRACT_MANAGER,
    CLINICAL_REVIEWER,
    COMPLIANCE_ANALYST,
    MEMBER_MATERIALS_MANAGER,
    DISTRIBUTOR_AGENT,
    FINANCE_ADMINISTRATOR,
)

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


def raw_user_id():
    return request.headers.get(USER_HEADER)


def raw_role():
    return request.headers.get(ROLE_HEADER)


def authenticate(allowed_roles, require_identity=True):
    """Rung 1 (authentication) then rung 2 (role admission).

    Returns the acting (user_id, role) pair.
    """
    user_id = raw_user_id()
    if require_identity and (user_id is None or str(user_id).strip() == ""):
        raise ApiError("ERR_UNAUTHENTICATED")
    role = raw_role()
    if role is None or role not in ALL_ROLES or role not in tuple(allowed_roles):
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def require_member_scope(acting_user_id, member_id):
    """Rung 3: the entity-backed MemberMaterialsManager acts only for itself."""
    if str(acting_user_id) != str(member_id):
        raise ApiError("ERR_MEMBER_SCOPE_VIOLATION")
