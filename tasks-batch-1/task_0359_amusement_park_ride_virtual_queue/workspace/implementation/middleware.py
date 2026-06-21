"""Auth header extraction and RBAC (PRD §2.1).

Auth headers (PRD §2.1):
  X-User-ID    — acting principal id
  X-User-Role  — one of {ParkAdmin, RideOperator, GuestApp}

Missing either header, or an unrecognized role -> ERR_UNAUTHENTICATED (401).
A recognized role attempting an operation outside its permissions -> ERR_UNAUTHORIZED (403).
"""
from flask import request

import errors

KNOWN_ROLES = {"ParkAdmin", "RideOperator", "GuestApp"}


def get_principal():
    """Return (user_id, role) after validating presence and known role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        errors.err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_roles(role, allowed):
    """ERR_UNAUTHORIZED if the acting role is not in the allowed set."""
    if role not in allowed:
        errors.err(errors.ERR_UNAUTHORIZED, "Role not permitted for this operation")
