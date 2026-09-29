"""Authentication, authorisation and ownership scope (PRD 2.1 / 2.5)."""

from flask import request

from errors import api_error

ROLES = (
    "CampDirector",
    "HealthCareStaff",
    "Visitor",
    "AccreditationOfficer",
    "StateLicensingAgent",
)

CAMP_SCOPED_ROLES = ("CampDirector", "HealthCareStaff")


class Identity(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allowed_roles):
    """Step 1 (401) then step 2 (403) of the validation ladder."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise api_error("ERR_UNAUTHENTICATED", "Missing or unrecognised authentication headers.")
    if role not in allowed_roles:
        raise api_error(
            "ERR_UNAUTHORIZED",
            "Role %s is not authorised for this operation." % role,
        )
    return Identity(user_id, role)


def require_camp_scope(ident, camp_id):
    """CampDirector / HealthCareStaff X-User-ID is the acting Camp id."""
    if ident.role in CAMP_SCOPED_ROLES and ident.user_id != camp_id:
        raise api_error(
            "ERR_FORBIDDEN_SCOPE",
            "The acting principal does not own the target resource.",
        )
