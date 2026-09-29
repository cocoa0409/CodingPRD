"""Authentication, endpoint RBAC, ownership, transition roles and SoD.

Tiers 1, 2, 6, 7 and 8 of the precedence ladder in PRD Section 2.11.
"""

from flask import request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

AGENCY_PRINCIPAL = "AgencyPrincipal"
LICENSING_ANALYST = "LicensingAnalyst"
ESCROW_AUDITOR = "EscrowAuditor"
UNDERWRITING_COUNSEL = "UnderwritingCounsel"
COMPLIANCE_OFFICER = "ComplianceOfficer"

ROLES = (
    AGENCY_PRINCIPAL,
    LICENSING_ANALYST,
    ESCROW_AUDITOR,
    UNDERWRITING_COUNSEL,
    COMPLIANCE_OFFICER,
)

ALL_ROLES = ROLES


def authenticate():
    """Tier 1 - both headers present and the role one of the five declared."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def require_roles(*allowed):
    """Tiers 1 then 2.  Returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def require_ownership(user_id, role, agency_id):
    """Tier 6 - an AgencyPrincipal acts only on its own agency's resources."""
    if role == AGENCY_PRINCIPAL and user_id != agency_id:
        raise ApiError("ERR_AGENCY_OWNERSHIP_REQUIRED")


def require_transition_role(role, allowed):
    """Tier 7 - the acting role is permitted for the specific transition."""
    if allowed is None:
        return
    if role not in allowed:
        raise ApiError("ERR_TRANSITION_ROLE_NOT_PERMITTED")


def require_segregation(user_id, recorded_user_id):
    """Tier 8 - SoD-1 and SoD-2 compare against a persisted actor identifier."""
    if recorded_user_id is not None and user_id == recorded_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
