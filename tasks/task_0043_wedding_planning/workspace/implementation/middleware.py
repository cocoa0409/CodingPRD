"""Auth header extraction and role checking helpers."""
from flask import request, g

from errors import (
    raise_error,
    ERR_MISSING_AUTH_HEADERS,
    ERR_INVALID_ROLE,
    ERR_NOT_OWNING_PLANNER,
    ERR_NOT_OWNING_VENDOR,
    ERR_AUDITOR_REQUIRED,
)

VALID_ROLES = {"Planner", "VendorRep", "Couple", "Auditor"}


def authenticate():
    """Validate auth headers. Sets g.user_id and g.user_role. Raises on failure."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role:
        raise_error(ERR_MISSING_AUTH_HEADERS, "Missing X-User-ID or X-User-Role")
    if user_role not in VALID_ROLES:
        raise_error(ERR_INVALID_ROLE, f"Unrecognized role: {user_role}")
    g.user_id = user_id
    g.user_role = user_role


def require_roles(*roles):
    """Ensure current actor's role is in the allowed set; otherwise pick the
    most appropriate forbidden error."""
    if g.user_role not in roles:
        # Determine which error to use. If the operation is auditor-exclusive but actor isn't auditor:
        if "Auditor" in roles and g.user_role != "Auditor":
            raise_error(ERR_AUDITOR_REQUIRED, "This operation requires Auditor role")
        if "Planner" in roles and g.user_role != "Planner":
            raise_error(ERR_NOT_OWNING_PLANNER, "This operation requires Planner role")
        if "VendorRep" in roles and g.user_role != "VendorRep":
            raise_error(ERR_NOT_OWNING_VENDOR, "This operation requires VendorRep role")
        # Generic fallback
        raise_error(ERR_AUDITOR_REQUIRED, "Forbidden role")


def check_planner_owns_project(project: dict):
    """If the role is Planner, the X-User-ID must match the project's planner_user_id."""
    if g.user_role == "Planner":
        if g.user_id != project.get("planner_user_id"):
            raise_error(ERR_NOT_OWNING_PLANNER, "Planner does not own this project")


def check_vendor_rep_owns_vendor(vendor: dict):
    if g.user_role == "VendorRep":
        if g.user_id != vendor.get("id"):
            raise_error(ERR_NOT_OWNING_VENDOR, "VendorRep does not own this vendor")
