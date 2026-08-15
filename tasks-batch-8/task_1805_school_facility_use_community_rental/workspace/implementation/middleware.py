"""Auth context: X-User-ID + X-User-Role header validation (PRD §2.1).

Five roles, spelled exactly: DistrictAdmin, FacilitiesDirector, SiteCoordinator,
CustodialSupervisor, RenterOrgRep. RenterOrgRep's X-User-ID is the id of the
acting RenterOrganization; all other roles' X-User-ID is opaque.
"""
from flask import request

import errors

ROLES = {
    "DistrictAdmin",
    "FacilitiesDirector",
    "SiteCoordinator",
    "CustodialSupervisor",
    "RenterOrgRep",
}


def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise errors.missing_context()
    if not role or role not in ROLES:
        raise errors.missing_context()
    return uid.strip(), role


def require_roles(*allowed):
    uid, role = get_auth()
    if role not in allowed:
        raise errors.forbidden()
    return uid, role


def require_rep_owns_org(org_id):
    """RenterOrgRep's X-User-ID must equal the renter org id in the path."""
    uid, role = get_auth()
    if role != "RenterOrgRep":
        raise errors.forbidden()
    if uid != org_id:
        raise errors.forbidden()
    return uid, role
