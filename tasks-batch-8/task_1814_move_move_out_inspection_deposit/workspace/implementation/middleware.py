"""Auth header extraction and role checks (PRD §2.1, validation priorities 1-2).

Headers: X-User-ID + X-User-Role. Roles: ManagerAdmin, PropertyManager,
Inspector, Tenant. Tenant is entity-backed by Tenancy: X-User-ID must equal
the tenancy id of the target resource on ownership-gated calls.
"""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
)

ALL_ROLES = ["ManagerAdmin", "PropertyManager", "Inspector", "Tenant"]


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: header presence and well-formedness."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must both be present and non-empty",
        )
    return Caller(user_id, role)


def check_role_allowed(caller: Caller, allowed_roles):
    """Priority 2: role membership in the endpoint's declared role list."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN_FOR_ROLE,
            f"role {caller.role} is not authorized for this endpoint",
        )


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller


def check_tenant_ownership(caller: Caller, tenancy_id):
    """Priority 2 (ownership leg): a Tenant caller may only touch resources
    whose tenancy_id equals their X-User-ID. Other roles are opaque."""
    if caller.role == "Tenant" and tenancy_id is not None:
        if caller.user_id != tenancy_id:
            raise_error(
                ERR_FORBIDDEN_FOR_ROLE,
                "Tenant X-User-ID does not match the target resource's tenancy",
            )
