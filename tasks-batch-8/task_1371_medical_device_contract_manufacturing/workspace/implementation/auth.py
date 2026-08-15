"""Auth context extraction and role permission checks (validation steps 1-2)."""
from flask import request

from errors import err_forbidden_role, err_user_context

QUALITY_ENGINEER = "QualityEngineer"
QUALITY_MANAGER = "QualityManager"
PRODUCTION_OPERATOR = "ProductionOperator"
SUPPLIER_QUALITY_ENGINEER = "SupplierQualityEngineer"
REGULATORY_AFFAIRS = "RegulatoryAffairs"
QMS_ADMIN = "QMSAdmin"

ROLES = {
    QUALITY_ENGINEER,
    QUALITY_MANAGER,
    PRODUCTION_OPERATOR,
    SUPPLIER_QUALITY_ENGINEER,
    REGULATORY_AFFAIRS,
    QMS_ADMIN,
}


def context():
    """Validation step 1: X-User-ID and X-User-Role present, role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_user_context()
    return uid, role


def require_role(role, *allowed):
    """Validation step 2: role permitted for this endpoint."""
    if role not in allowed:
        raise err_forbidden_role()
