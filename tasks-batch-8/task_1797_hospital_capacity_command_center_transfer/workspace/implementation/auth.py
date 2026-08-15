"""Auth middleware: X-User-ID / X-User-Role header checks and RBAC (PRD 2.1)."""

import functools
from flask import request, g
import errors
from store import db

ALL_ROLES = {
    "SystemAdministrator",
    "BedManager",
    "TransferCenterCoordinator",
    "AcceptingPhysician",
    "HouseSupervisor",
    "CapacityPlanner",
    "Any",
}


def require_roles(*roles):
    """Decorator enforcing priority 1 (headers) and priority 2 (role) checks."""

    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            uid = request.headers.get("X-User-ID", "")
            role = request.headers.get("X-User-Role", "")
            if uid is None or role is None or not uid.strip() or not role.strip():
                raise errors.err(
                    errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    400,
                    "X-User-ID and X-User-Role headers must be present and non-empty",
                )
            uid = uid.strip()
            role = role.strip()
            if role not in ALL_ROLES:
                raise errors.err(errors.ERR_INSUFFICIENT_PERMISSIONS, 403, "Unrecognized role")
            # Entity-backed role: AcceptingPhysician's X-User-ID must resolve to a Physician.
            if role == "AcceptingPhysician" and uid not in db.physicians:
                raise errors.err(
                    errors.ERR_INSUFFICIENT_PERMISSIONS,
                    403,
                    "X-User-ID does not resolve to a Physician",
                )
            if "Any" not in roles and role not in roles:
                raise errors.err(
                    errors.ERR_INSUFFICIENT_PERMISSIONS,
                    403,
                    "Role not permitted for this endpoint",
                )
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)

        return inner

    return wrap
