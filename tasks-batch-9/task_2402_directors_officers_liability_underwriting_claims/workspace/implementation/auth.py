"""Header authentication, role authorisation and RiskManager ownership (PRD 2.1)."""

from flask import request

from errors import ApiError

UNDERWRITER = "Underwriter"
RISK_MANAGER = "RiskManager"
CLAIMS_ADJUSTER = "ClaimsAdjuster"
COMPLIANCE_OFFICER = "ComplianceOfficer"

ALL_ROLES = (UNDERWRITER, RISK_MANAGER, CLAIMS_ADJUSTER, COMPLIANCE_OFFICER)


def authenticate(*allowed_roles):
    """Ladder steps 1 and 2: authentication then role authorisation."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def require_owner(role, user_id, insured_id):
    """Ladder step 4: ownership, for a RiskManager only."""
    if role == RISK_MANAGER and user_id != insured_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
