"""Auth context extraction and RBAC checks (PRD §2.1).

Two mandatory headers:
  X-User-ID   -> acting operator (opaque)
  X-User-Role -> operational capacity

Roles recognized (PRD §2.1, spelled precisely):
  ComplianceOfficer, AccountManager, FieldTechnician, PlantOperator, DestructionWitness
"""
from flask import request

from errors import err

VALID_ROLES = {
    "ComplianceOfficer",
    "AccountManager",
    "FieldTechnician",
    "PlantOperator",
    "DestructionWitness",
}


def get_auth():
    """Extract and validate the auth context.

    Missing or malformed header -> ERR_MISSING_AUTH_CONTEXT (401).
    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_MISSING_AUTH_CONTEXT", "Missing X-User-ID or X-User-Role header")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise err("ERR_MISSING_AUTH_CONTEXT", "Malformed X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        # A role string that is not one of the recognized roles is a malformed
        # auth context (not a forbidden-role case, which presumes a valid role).
        raise err("ERR_MISSING_AUTH_CONTEXT", "Unrecognized role: %s" % role)
    return user_id, role


def require_role(role, allowed):
    """Role authorization (PRD §2.1): well-formed but unpermitted role -> 403."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation" % role)
