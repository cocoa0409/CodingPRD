"""Authentication (rung 1), role authorization (rung 2) and ownership (rung 5)."""

from flask import request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

PLATFORM_ADMIN = "PlatformAdmin"
FEED_INTEGRATOR = "FeedIntegrator"
MOVE_OPS_AGENT = "MoveOpsAgent"
COMPLIANCE_OFFICER = "ComplianceOfficer"
RESIDENT = "Resident"
PROVIDER_AGENT = "ProviderAgent"
PARTNER_AGENT = "PartnerAgent"
EXTERNAL_SERVICE_GATEWAY = "ExternalServiceGateway"

ALL_ROLES = (
    PLATFORM_ADMIN,
    FEED_INTEGRATOR,
    MOVE_OPS_AGENT,
    COMPLIANCE_OFFICER,
    RESIDENT,
    PROVIDER_AGENT,
    PARTNER_AGENT,
    EXTERNAL_SERVICE_GATEWAY,
)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def is_role(self, *roles):
        return self.role in roles

    def own(self, owner_value):
        """Rung 5: entity-backed roles may only touch rows they identify with."""
        if str(owner_value) != str(self.user_id):
            raise ApiError(
                "ERR_OWNERSHIP_VIOLATION",
                "The caller does not own the addressed resource.",
            )

    def own_if(self, role, owner_value):
        if self.role == role:
            self.own(owner_value)


def authenticate(*allowed_roles):
    """Rungs 1 and 2 of the validation ladder, in that order."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "Missing %s header." % USER_ID_HEADER)
    if not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "Missing %s header." % USER_ROLE_HEADER)
    role = role.strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    allowed = set(allowed_roles) | {PLATFORM_ADMIN}
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role %s may not perform this operation." % role,
        )
    return Caller(str(user_id).strip(), role)
