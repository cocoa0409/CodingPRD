"""Auth header extraction and role checking (PRD 2.1).

Every request must carry two mandatory headers:
  X-User-ID   — identifies the acting user
  X-User-Role — declares the operational capacity

Recognized roles: LightingDesigner, InstallTech, ControlProgrammer, Customer,
OperationsAdmin. Missing either header (or unknown role) -> ERR_UNAUTHENTICATED.
Authenticated but role not permitted for the operation -> ERR_FORBIDDEN_ROLE.

For the Customer role, X-User-ID is the id of the acting Customer entity; for
the other four (opaque) roles, X-User-ID is an opaque operator handle not tied
to any persisted entity.
"""

from flask import request

from errors import err

VALID_ROLES = {
    "LightingDesigner",
    "InstallTech",
    "ControlProgrammer",
    "Customer",
    "OperationsAdmin",
}


def get_auth():
    """Validate the two mandatory auth headers (priority 1). Returns
    (user_id, role). A request missing either header, or carrying an unknown
    role, is ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header.")
    if user_id == "" or role == "":
        raise err("ERR_UNAUTHENTICATED", "Empty X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unrecognized X-User-Role header.")
    return user_id, role


def require_role(role, allowed):
    """Role permission check (priority 2). ERR_FORBIDDEN_ROLE on failure."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation.")
