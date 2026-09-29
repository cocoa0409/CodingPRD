"""Authentication, role gating, and the scoped-ownership checks.

Implements steps 1..8 of the pinned rejection order (PRD 2.11).  Steps 9 and 10
(segregation of duties) live with the endpoints that own them because they need
the target resource, but they are still applied before path resolution.
"""

from flask import request

from db import db
from errors import ApiError

ROLE_NAMES = (
    "PlatformAdmin",
    "StaffingCoordinator",
    "FacilityAdministrator",
    "VendorRepresentative",
    "StateAuditor",
    "CmsPublisher",
    "AppealsReviewer",
)

# The two Worker-backed roles and the literal string each one needs to find in
# the acting Worker's authorized_roles array.
WORKER_BACKED = {
    "StaffingCoordinator": "STAFFING_COORDINATOR",
    "FacilityAdministrator": "FACILITY_ADMINISTRATOR",
}

AUTHORIZED_ROLE_VALUES = ("STAFFING_COORDINATOR", "FACILITY_ADMINISTRATOR")


class Actor(object):
    __slots__ = ("role", "user_id", "worker", "vendor")

    def __init__(self, role, user_id, worker=None, vendor=None):
        self.role = role
        self.user_id = user_id
        self.worker = worker
        self.vendor = vendor

    @property
    def worker_id(self):
        return self.worker["id"] if self.worker else None


def auth(*allowed_roles):
    """Steps 1 through 6."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLE_NAMES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")

    worker = None
    vendor = None
    if role in WORKER_BACKED:
        worker = db.workers.get(user_id)
        if worker is None:
            raise ApiError("ERR_IDENTITY_NOT_FOUND")
        if WORKER_BACKED[role] not in (worker.get("authorized_roles") or []):
            raise ApiError("ERR_WORKER_ROLE_NOT_AUTHORIZED")
        if worker.get("status") != "ACTIVE":
            raise ApiError("ERR_ACTOR_INACTIVE")
    elif role == "VendorRepresentative":
        vendor = db.vendors.get(user_id)
        if vendor is None:
            raise ApiError("ERR_IDENTITY_NOT_FOUND")
    return Actor(role, user_id, worker, vendor)


def facility_scope(actor, facility_id):
    """Step 7 — write endpoints acting as a Worker-backed role.

    ``facility_id`` may be None when the target cannot be resolved yet; the
    check is then skipped so that path/body resolution can raise the proper
    not-found code at step 11 or 12.
    """
    if actor.worker is None or facility_id is None:
        return
    if actor.worker.get("facility_id") != facility_id:
        raise ApiError("ERR_FACILITY_SCOPE_VIOLATION")


def vendor_scope(actor, vendor_id):
    """Step 8 — batch creation, submission, and revocation as a vendor rep."""
    if actor.role != "VendorRepresentative" or vendor_id is None:
        return
    if actor.user_id != vendor_id:
        raise ApiError("ERR_VENDOR_SCOPE_VIOLATION")
