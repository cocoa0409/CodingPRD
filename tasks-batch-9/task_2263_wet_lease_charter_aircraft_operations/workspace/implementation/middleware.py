"""Authentication, RBAC and lessee-ownership enforcement (PRD 2.1 / 2.4 / 2.8)."""

from flask import request

from db import db
from errors import ApiError

LESSOR_OPS = "LessorOpsController"
LESSEE = "Lessee"
REGULATORY_AUTHORITY = "RegulatoryAuthority"
MAINTENANCE_CONTROLLER = "MaintenanceController"
BILLING_ADMIN = "BillingAdmin"
INSURANCE_UNDERWRITER = "InsuranceUnderwriter"

ALL_ROLES = (
    LESSOR_OPS,
    LESSEE,
    REGULATORY_AUTHORITY,
    MAINTENANCE_CONTROLLER,
    BILLING_ADMIN,
    INSURANCE_UNDERWRITER,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_lessee(self):
        return self.role == LESSEE


def authenticate():
    """Validation step 1 — both headers present and the role a declared member."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return Actor(str(user_id).strip(), role)


def authorize(actor, allowed_roles):
    """Validation step 2 — the acting role must be listed for the endpoint."""
    if actor.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return actor


def require(allowed_roles):
    return authorize(authenticate(), allowed_roles)


# --------------------------------------------------------------------------
# lessee ownership
# --------------------------------------------------------------------------

def owning_lessee_id(kind, row):
    """Return the lessee id that owns `row`, or None when it has no owner."""
    if row is None:
        return None
    if kind == "lessee":
        return row["id"]
    if kind == "lease":
        return row["lessee_id"]
    if kind == "aircraft":
        lease_id = row.get("assigned_lease_id")
        lease = db.leases.get(lease_id) if lease_id else None
        return lease["lessee_id"] if lease else None
    lease_id = row.get("lease_id")
    lease = db.leases.get(lease_id) if lease_id else None
    return lease["lessee_id"] if lease else None


def check_ownership(actor, kind, row):
    """Validation step 6 — a Lessee may only touch its own lease's resources."""
    if not actor.is_lessee:
        return
    owner = owning_lessee_id(kind, row)
    if owner is None or owner != actor.user_id:
        raise ApiError("ERR_UNAUTHORIZED")


def scope_for_lessee(actor, kind, rows):
    """List reads by a Lessee are narrowed to that lessee's own rows."""
    if not actor.is_lessee:
        return rows
    kept = []
    for row in rows:
        owner = owning_lessee_id(kind, row)
        if owner is None or owner == actor.user_id:
            kept.append(row)
    return kept
