"""Authentication, role authorization and CustomerContact account scope.

Rungs 1-3 of the rejection ladder (PRD 2.7).
"""
from flask import request

from errors import ApiError

PLANT_ROLES = (
    "PlantManager",
    "IntakeClerk",
    "Technician",
    "CertifyingInspector",
    "ComplianceOfficer",
)
ALL_ROLES = PLANT_ROLES + ("CustomerContact",)

ROLE_HEADER = "X-User-Role"
USER_HEADER = "X-User-ID"


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


class Caller(object):
    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_customer(self):
        return self.role == "CustomerContact"


def authorize(allowed_roles, auth_exempt=False):
    """Rung 1 (authentication) then rung 2 (role authorization).

    `auth_exempt` is used only by POST /_clock/set_current_utc, which PRD 2.1
    exempts from the authentication gate so a harness can position the clock
    before establishing any identity; the role gate still applies to any role
    that IS presented, and excludes CustomerContact.
    """
    role = _header(ROLE_HEADER)
    user_id = _header(USER_HEADER)

    if not auth_exempt:
        if role is None:
            raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
        if role == "CustomerContact" and user_id is None:
            raise ApiError(
                "ERR_UNAUTHENTICATED",
                "X-User-ID header is required for CustomerContact callers.",
            )

    if role is not None and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s is not authorized for this endpoint." % role)

    return Caller(role, user_id)


def check_account_scope(caller, account_id):
    """Rung 3: a CustomerContact may only read its own program's data."""
    if caller.is_customer and account_id != caller.user_id:
        raise ApiError("ERR_ACCOUNT_SCOPE_VIOLATION",
                       "This resource belongs to another customer account.")
