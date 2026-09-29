"""Principal extraction and RBAC (PRD section 2.1, validation order steps 1-2)."""

from flask import request

from errors import fail

ROLES = (
    "PlatformAdmin",
    "AcquisitionAnalyst",
    "PortfolioManager",
    "TreasuryOfficer",
    "TitleOfficer",
    "Lender",
    "ServicingAgent",
    "Landowner",
    "TowerCompanyAgent",
)


def principal(*allowed_roles):
    """Step 1 authentication then step 2 endpoint role permission."""
    role = request.headers.get("X-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    if allowed_roles and role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    return user_id, role
