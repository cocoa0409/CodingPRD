"""Auth header extraction and role gating (PRD §2.1)."""
from flask import request

from errors import ApiError, ERR_AUTH, ERR_FORBIDDEN

ROLE_WORKOUT_OFFICER = "WorkoutOfficer"
ROLE_SPECIAL_ASSETS_MANAGER = "SpecialAssetsManager"
ROLE_CREDIT_COMMITTEE = "CreditCommittee"
ROLE_APPRAISAL_DESK = "AppraisalDesk"
ROLE_LEGAL_COUNSEL = "LegalCounsel"
ROLE_LOAN_ACCOUNTING = "LoanAccounting"
ROLE_PORTFOLIO_ANALYST = "PortfolioAnalyst"
ROLE_SYSTEM_ADMIN = "SystemAdmin"

ALL_ROLES = (
    ROLE_WORKOUT_OFFICER,
    ROLE_SPECIAL_ASSETS_MANAGER,
    ROLE_CREDIT_COMMITTEE,
    ROLE_APPRAISAL_DESK,
    ROLE_LEGAL_COUNSEL,
    ROLE_LOAN_ACCOUNTING,
    ROLE_PORTFOLIO_ANALYST,
    ROLE_SYSTEM_ADMIN,
)


def actor():
    """Validate X-User-ID / X-User-Role; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str):
        raise ApiError(ERR_AUTH, 400, "X-User-ID header is missing")
    if not role or role not in ALL_ROLES:
        raise ApiError(ERR_AUTH, 400, "X-User-Role header is missing or unrecognized")
    return user_id, role


def require_roles(*roles):
    user_id, role = actor()
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN, 403, "Role is not authorized for this endpoint")
    return user_id, role


def require_any_role():
    return actor()
