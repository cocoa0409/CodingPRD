"""Auth: X-User-ID / X-User-Role headers, role-permission gate (PRD §2.1)."""
from flask import request

from errors import err_bad_context, err_forbidden

ROLES = {
    "DealershipAdmin",
    "SalesManager",
    "SalesConsultant",
    "ServiceManager",
    "ServiceAdvisor",
    "PartsCounterRep",
    "WarrantyAdministrator",
    "OEMClaimsAdjudicator",
    "Controller",
    "FleetCustomer",
}

ALL_ROLES = sorted(ROLES)


def caller(allowed_roles):
    """Validate headers (priority 1) then endpoint role permission (priority 2)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_bad_context()
    if role not in allowed_roles:
        raise err_forbidden()
    return uid, role
