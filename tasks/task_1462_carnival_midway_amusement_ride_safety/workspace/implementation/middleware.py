"""Authentication and authorization (validation families 1-3).

Family 1: X-User-Role / X-User-ID present and non-blank -> ERR_UNAUTHENTICATED 401.
Family 2: role admitted by the endpoint -> ERR_FORBIDDEN 403.
Family 3: entity-backed scoping -> ERR_FORBIDDEN 403:
  - StateProgramAdmin: opaque, no entity check.
  - StateInspector: X-User-ID must be an Inspector.id with active == true.
  - Staff roles: X-User-ID must be an ACTIVE StaffMember carrying the role's
    function, with fair_id matching the endpoint's primary resource's fair.
"""
from flask import g, request

import db
from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ALL_ROLES = [
    "StateProgramAdmin",
    "StateInspector",
    "FairManager",
    "RideOperator",
    "TicketClerk",
    "CrewMember",
]

ROLE_FUNCTION = {
    "FairManager": "SUPERVISOR",
    "RideOperator": "OPERATOR",
    "TicketClerk": "CLERK",
    "CrewMember": "CREW",
}


def authenticate(allowed_roles):
    """Run validation families 1-3 up to identity resolution.

    Returns the caller context dict. Fair scoping (against the primary
    resource) is applied separately via scope_to_fair() once the resource is
    resolvable.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None or role.strip() == "" or user_id.strip() == "":
        raise_err(ERR_UNAUTHENTICATED, "X-User-Role and X-User-ID headers are required")
    if role not in ALL_ROLES or role not in allowed_roles:
        raise_err(ERR_FORBIDDEN, "Role %s is not admitted to this endpoint" % role)

    ctx = {"role": role, "user_id": user_id, "staff": None, "inspector": None}
    if role == "StateProgramAdmin":
        pass  # opaque identity
    elif role == "StateInspector":
        inspector = db.get("inspectors", user_id)
        if inspector is None or inspector.get("active") is not True:
            raise_err(ERR_FORBIDDEN, "Caller is not an active inspector")
        ctx["inspector"] = inspector
    else:
        staff = db.get("staff", user_id)
        if staff is None or staff.get("status") != "ACTIVE":
            raise_err(ERR_FORBIDDEN, "Caller is not an active staff member")
        if ROLE_FUNCTION[role] not in staff.get("functions", []):
            raise_err(ERR_FORBIDDEN, "Staff member does not carry the required function")
        ctx["staff"] = staff
    g.auth = ctx
    return ctx


def scope_to_fair(ctx, fair_id):
    """Family 3 fair scoping for staff-backed callers against the primary
    resource's fair. No-op for admin/inspector callers or when the fair cannot
    be determined (deferred to the 404 tier)."""
    if fair_id is None:
        return
    staff = ctx.get("staff")
    if staff is not None and staff["fair_id"] != fair_id:
        raise_err(ERR_FORBIDDEN, "Staff member belongs to a different fair")


def require_owner(condition):
    if not condition:
        raise_err(ERR_FORBIDDEN, "Caller is not the resource owner")
