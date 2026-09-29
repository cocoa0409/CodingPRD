"""Ladder tier A: authentication, role admission, scope binding, two-person control.

PRD section 2.1 fixes the header names as X-User-ID and X-User-Role.
"""
from flask import request

from errors import ApiError

ROSTER_OPERATOR = "RosterOperator"
DATA_GOVERNANCE_OFFICER = "DataGovernanceOfficer"
VENDOR_INTEGRATION_MANAGER = "VendorIntegrationManager"
BUILDING_LICENSE_ADMIN = "BuildingLicenseAdmin"
IDENTITY_ADMIN = "IdentityAdmin"

ALL_ROLES = (
    ROSTER_OPERATOR,
    DATA_GOVERNANCE_OFFICER,
    VENDOR_INTEGRATION_MANAGER,
    BUILDING_LICENSE_ADMIN,
    IDENTITY_ADMIN,
)


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """(1) Both headers present and non-blank, else ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    return Actor(user_id, role)


def require(*roles):
    """(1) then (2): the role must be admitted by the target operation."""
    actor = authenticate()
    if actor.role not in roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return actor


def vendor_scope(actor, vendor_app):
    """(3) VendorIntegrationManager is bound to licenses it registered.

    Evaluated BEFORE existence checks, so `vendor_app` may be None: a probe
    against an unknown or foreign identifier learns only that it is out of
    scope, never whether the identifier exists.
    """
    if actor.role != VENDOR_INTEGRATION_MANAGER:
        return
    if vendor_app is None or vendor_app.get("created_by_user_id") != actor.user_id:
        raise ApiError("ERR_SCOPE_VIOLATION")


def building_scope(actor, allocation):
    """(3) BuildingLicenseAdmin may only write its own building's allocation."""
    if actor.role != BUILDING_LICENSE_ADMIN:
        return
    if allocation is None or allocation.get("school_id") != actor.user_id:
        raise ApiError("ERR_SCOPE_VIOLATION")


def segregation(actor, other_user_id):
    """(4) Two-person control: the actor may not be the recorded first party."""
    if other_user_id is not None and actor.user_id == other_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
