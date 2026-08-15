"""Auth middleware: identity headers, role authorization, VesselAgent scope.

PRD 2.1: every request carries X-User-ID and X-User-Role. A missing/unknown
role or missing user id -> ERR_UNAUTHENTICATED (401). A declared role not
permitted on the endpoint -> ERR_FORBIDDEN (403). A VesselAgent acts only on
its own vessel's port calls and their child records (ERR_VESSEL_SCOPE, 403).
"""

from flask import request

import db
from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    ERR_VESSEL_SCOPE,
)

ROLES = {
    "PortAuthorityAdmin",
    "Harbormaster",
    "TerminalOperator",
    "VesselAgent",
    "CustomsOfficer",
    "BillingClerk",
}

# "Any authenticated role" list endpoints.
ANY = ROLES

VESSEL_AGENT = "VesselAgent"


def authenticate(allowed_roles):
    """Pipeline priority 1 (authentication) then 2 (role authorization).
    Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES or user_id is None or not user_id.strip():
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "X-User-Role must name a declared role and X-User-ID must be present",
        )
    if role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN,
            403,
            f"role {role} is not authorized for this endpoint",
        )
    return user_id, role


def scope_call(user_id, role, call):
    """Pipeline priority 4: a VesselAgent may only act on its own vessel's
    port call (call already resolved)."""
    if role == VESSEL_AGENT and call is not None and call["vessel_id"] != user_id:
        raise ApiError(
            ERR_VESSEL_SCOPE,
            403,
            "vessel agent may only act on its own vessel's port calls",
        )


def call_of(entity):
    """Resolve the owning PortCall of a child entity (None when unlinked)."""
    if entity is None:
        return None
    call_id = entity.get("port_call_id")
    if not call_id:
        return None
    return db.get("port_calls", call_id)


def scope_entity(user_id, role, entity):
    """VesselAgent scope for a child record attached to a port call."""
    if role == VESSEL_AGENT:
        scope_call(user_id, role, call_of(entity))
