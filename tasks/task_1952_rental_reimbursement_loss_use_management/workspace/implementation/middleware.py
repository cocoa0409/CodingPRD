from flask import request

from errors import api_error

ALL_ROLES = [
    "Customer",
    "RentalDeskAgent",
    "ClaimsAdjuster",
    "SettlementApprover",
    "RepairShop",
    "RentalPartner",
    "RecoverySpecialist",
    "SystemAdmin",
]


class Caller:
    def __init__(self, user_id, role):
        self.id = user_id
        self.role = role


def require_roles(allowed):
    """Rung 1 (header presence) then rung 2 (role authorization)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or not role.strip():
        raise api_error(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    if role not in allowed:
        raise api_error(
            "ERR_INSUFFICIENT_PERMISSIONS",
            403,
            "role %s is not authorized for this endpoint" % role,
        )
    return Caller(uid.strip(), role.strip())
