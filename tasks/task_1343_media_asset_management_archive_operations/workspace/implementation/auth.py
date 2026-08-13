"""Authentication context and role-based authorization (PRD section 2.1)."""
from flask import request

from errors import raise_err

ALL_ROLES = [
    "SystemAdmin",
    "IngestCoordinator",
    "MetadataCataloger",
    "MetadataLibrarian",
    "ArchivistLead",
    "RightsManager",
    "LegalCounsel",
    "AccessOfficer",
    "Requester",
    "FinanceOfficer",
    "LabTechnician",
]


def auth_ctx():
    """Step 1: both X-User-ID and X-User-Role present and non-empty."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not str(uid).strip() or role is None or not str(role).strip():
        raise_err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return uid, role


def require_roles(*allowed):
    """Steps 1-2: auth context present; role permitted for the operation."""
    uid, role = auth_ctx()
    if role not in allowed:
        raise_err(
            "ERR_INSUFFICIENT_PERMISSIONS",
            f"Role {role} is not permitted to perform this operation",
        )
    return uid, role
