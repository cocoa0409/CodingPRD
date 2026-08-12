"""Auth header extraction and role enforcement (PRD §2.1, SCAFFOLD §1.4 priorities 1-2).

Headers: X-User-ID, X-User-Role.
Roles: SugarhouseManager, FieldCrew, SugarMaker, CertInspector.

Entity-backed roles (FieldCrew, SugarMaker): X-User-ID is the acting CrewMember.id.
Opaque roles (SugarhouseManager, CertInspector): X-User-ID is not entity-compared.
"""

from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE

ROLES = {"SugarhouseManager", "FieldCrew", "SugarMaker", "CertInspector"}
ENTITY_BACKED = {"FieldCrew", "SugarMaker"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority 1: headers present and role declared."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise_err(ERR_UNAUTHENTICATED, "missing X-User-Role or X-User-ID header")
    if role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, f"unknown role: {role}")
    return Caller(user_id=user_id, role=role)


def require_role(caller, allowed_roles):
    """Priority 2 (role gate): caller's role must be in allowed set."""
    if caller.role not in allowed_roles:
        raise_err(ERR_UNAUTHORIZED_ROLE, f"role {caller.role} not permitted on this endpoint")


def enforce_entity_identity(caller, field_value, field_name):
    """Priority 2 (entity-backed identity): for FieldCrew/SugarMaker callers,
    X-User-ID must equal the operator reference field in the body.
    SugarhouseManager and CertInspector are opaque — no comparison.
    """
    if caller.role in ENTITY_BACKED:
        if field_value is not None and caller.user_id != field_value:
            raise_err(
                ERR_UNAUTHORIZED_ROLE,
                f"{field_name} must equal X-User-ID for role {caller.role}",
            )
