"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import request

from db import DB
from errors import ApiError

ROLES = [
    "CashOperationsAdmin",
    "VaultCustodian",
    "FedCoordinator",
    "CarrierDispatcher",
    "AtmAnalyst",
    "ComplianceOfficer",
]

# Site-scoped staff roles whose X-User-ID must resolve to an active StaffMember.
SITE_SCOPED_STAFF_ROLES = {
    "VaultCustodian",
    "FedCoordinator",
    "AtmAnalyst",
    "ComplianceOfficer",
}

# Roles allowed on every standard read (GET) endpoint.
ALL_ROLES = list(ROLES)


class Principal:
    def __init__(self, user_id, role, staff=None, carrier=None):
        self.user_id = user_id
        self.role = role
        self.staff = staff
        self.carrier = carrier

    @property
    def home_site_id(self):
        return self.staff["home_site_id"] if self.staff else None


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; optionally enforce an endpoint role set.

    Returns a Principal. Auth priority (scaffold validations 1-3):
      1. headers present, role declared, entity-backed identity resolves active
      2. role permitted for endpoint
      3. site-scope / carrier-ownership (checked by callers via require_site_scope)
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )

    staff = None
    carrier = None
    if role in SITE_SCOPED_STAFF_ROLES:
        staff = DB["staff_members"].get(user_id)
        if staff is None or not staff.get("active", True):
            raise ApiError(
                "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                400,
                "X-User-ID does not resolve to an existing active StaffMember",
            )
    elif role == "CarrierDispatcher":
        carrier = DB["carriers"].get(user_id)
        if carrier is None:
            raise ApiError(
                "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                400,
                "X-User-ID does not resolve to an existing Carrier",
            )
    # CashOperationsAdmin: opaque identity, no entity resolution.

    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            403,
            "Role not permitted for this endpoint",
        )
    return Principal(user_id, role, staff=staff, carrier=carrier)


def require_site_scope(principal, site_id):
    """Site-scoped staff roles may only act on resources of their home site.

    CashOperationsAdmin (global) and CarrierDispatcher (carrier-scoped) are exempt.
    """
    if site_id is None:
        return
    if principal.role in SITE_SCOPED_STAFF_ROLES:
        if principal.home_site_id != site_id:
            raise ApiError(
                "ERR_SITE_SCOPE_VIOLATION",
                403,
                "Site-scoped staff may only act on resources of their home site",
            )


def require_carrier_ownership(principal, shipment):
    """CarrierDispatcher may only act on shipments whose carrier_id == X-User-ID."""
    if principal.role == "CarrierDispatcher":
        if shipment.get("carrier_id") != principal.user_id:
            raise ApiError(
                "ERR_RESOURCE_OWNERSHIP_VIOLATION",
                403,
                "CarrierDispatcher may only act on their own carrier's shipments",
            )
