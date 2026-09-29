"""Identity, role authorisation and regulatory scope (PRD §2.1, ladder steps 1-2, 5)."""

from flask import request

from db import db
from errors import ApiError

ROLES = (
    "PlatformAdmin",
    "LicensingManager",
    "ComplianceOfficer",
    "ChiefComplianceOfficer",
    "StateRegulator",
    "DelegateOperator",
)

NON_TERMINAL_APPLICATION_STATUSES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "DEFICIENT")


def authorize(*allowed_roles):
    """Ladder step 1 (ERR_UNAUTHENTICATED) then step 2 (ERR_UNAUTHORIZED)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unrecognised identity headers")
    if role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s may not call %s %s" % (role, request.method, request.path),
        )
    return user_id, role


def require_scope(condition, user_id, resource):
    if not condition:
        raise ApiError(
            "ERR_FORBIDDEN_SCOPE", "Actor %s is outside the scope of %s" % (user_id, resource)
        )


def regulator_matches(user_id, jurisdiction_id):
    return jurisdiction_id is not None and user_id == jurisdiction_id


def regulator_has_licensee_nexus(user_id, licensee_id):
    """PRD §2.1: for control-person actions the acting jurisdiction must be one
    where the licensee holds an ACTIVE StateLicense or has a LicenseApplication
    in a non-terminal status."""
    for lic in db.state_licenses.values():
        if (
            lic["licensee_id"] == licensee_id
            and lic["jurisdiction_id"] == user_id
            and lic["license_status"] == "ACTIVE"
        ):
            return True
    for app in db.applications.values():
        if (
            app["licensee_id"] == licensee_id
            and app["jurisdiction_id"] == user_id
            and app["status"] in NON_TERMINAL_APPLICATION_STATUSES
        ):
            return True
    return False
