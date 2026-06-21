"""Auth header extraction and RBAC enforcement (PRD §2.1, §1.7).

Every request carries X-User-ID (opaque operator id) and X-User-Role (one of the
five recognised roles). Missing either header -> ERR_UNAUTHENTICATED (401). A
present-but-unpermitted role for the operation -> ERR_UNAUTHORIZED (403). These
two checks run before existence/state/business validation (PRD §3.9).
"""

from flask import request

from errors import err

ROLES = {
    "IntakeAgent",
    "PrivacyOfficer",
    "FulfillmentWorker",
    "ProcessorAgent",
    "DataSubjectAgent",
}


def get_identity():
    """Return (user_id, role) from headers, raising ERR_UNAUTHENTICATED if either
    is absent or empty."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    return user_id, role


def require_roles(allowed_roles):
    """Authenticate, then authorise the caller's role against allowed_roles.

    Returns (user_id, role). An unrecognised or unpermitted role yields
    ERR_UNAUTHORIZED (403) — only after authentication has passed.
    """
    user_id, role = get_identity()
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role '%s' is not permitted for this operation" % role)
    return user_id, role
