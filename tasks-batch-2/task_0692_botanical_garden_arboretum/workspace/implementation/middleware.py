"""Auth header extraction and role checking (PRD §2.1)."""
from flask import request

import errors

# The five roles, spelled precisely (PRD §2.1).
KNOWN_ROLES = {
    "GardenAdmin",
    "GardenStaff",
    "RentalCoordinator",
    "DevelopmentOfficer",
    "Visitor",
}


def get_identity():
    """Validate auth headers (priority 1: ERR_UNAUTHENTICATED).

    Every request must carry X-User-ID and X-User-Role. If either header is
    absent, reject with ERR_UNAUTHENTICATED (401) before any other processing.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise errors.unauthenticated()
    if role not in KNOWN_ROLES:
        # An unrecognized role cannot be permitted for any operation.
        raise errors.forbidden_role()
    return user_id, role


def require_role(role, allowed):
    """Role permission check (priority 2: ERR_FORBIDDEN_ROLE)."""
    if role not in allowed:
        raise errors.forbidden_role()
