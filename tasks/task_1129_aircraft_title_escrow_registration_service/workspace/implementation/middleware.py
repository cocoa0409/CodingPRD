"""Auth middleware per scaffold §1.4 validations 1-3 and PRD §2.1."""

from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_FORBIDDEN_IDENTITY,
)

KNOWN_ROLES = {"EscrowOfficer", "EscrowManager", "LenderRep", "Auditor"}
ALL_ROLES = ["EscrowOfficer", "EscrowManager", "LenderRep", "Auditor"]


def get_auth():
    """Return (user_id, role). Raises ApiError if headers missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "Missing or invalid X-User-ID / X-User-Role headers.",
            401,
        )
    return user_id, role


def require_roles(allowed_roles):
    """Verify role is in the endpoint's allowed list."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            f"Role {role} is not authorized for this endpoint.",
            403,
        )
    return user_id, role


def require_lender_identity(lienor_party_id: str):
    """For LenderRep endpoints: X-User-ID must equal the lien's lienor_party_id."""
    user_id, role = require_roles(["LenderRep"])
    if user_id != lienor_party_id:
        raise ApiError(
            ERR_FORBIDDEN_IDENTITY,
            "LenderRep identity does not match the lien's lienor_party_id.",
            403,
        )
    return user_id, role
