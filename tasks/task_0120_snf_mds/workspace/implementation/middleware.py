"""Auth header extraction and RBAC checks (PRD §2.1, §2.7).

Auth headers (verbatim from PRD §2.1):
  X-User-ID   — opaque acting-operator id
  X-User-Role — one of the six peer roles below

Validation order (PRD §2.7): authentication first (ERR_UNAUTHENTICATED), then
role authorization (ERR_FORBIDDEN_ROLE). Existence / body / state / business
checks happen later inside the route handlers.

X-User-ID is an opaque operator identifier for all six roles; it is never
compared to any entity id and never determines ownership (PRD §2.1).
"""
from flask import request

import errors

ROLES = {
    "Administrator",
    "AdmissionsCoordinator",
    "MdsCoordinator",
    "Therapist",
    "Physician",
    "BillingAnalyst",
}


def get_identity():
    """Return (user_id, role), enforcing presence of both headers (PRD §2.1).

    Missing or empty X-User-ID or X-User-Role -> ERR_UNAUTHENTICATED. An
    unrecognized role value is treated as not-permitted for any operation, so
    it surfaces as ERR_FORBIDDEN_ROLE at the authorization gate rather than
    here; but per §2.1 the headers themselves must merely be present/non-empty.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "missing X-User-ID or X-User-Role")
    return user_id, role


def require_role(role, allowed):
    """Priority-2 role authorization: ERR_FORBIDDEN_ROLE if role not permitted."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "role not permitted for this operation")
