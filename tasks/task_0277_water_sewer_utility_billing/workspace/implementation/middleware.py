"""Auth header extraction and role/ownership checks (PRD §2.1, §2.9).

Headers: X-User-ID (acting principal), X-User-Role (operational capacity).
Roles: BillingClerk, FieldOps, AssistanceCaseworker, Customer.

For Customer, X-User-ID is the id of the acting Account (entity_backed). For the
three operator roles, X-User-ID is opaque and never matched against an entity.
"""
from flask import request

import errors

ROLES = {"BillingClerk", "FieldOps", "AssistanceCaseworker", "Customer"}


def get_role():
    return request.headers.get("X-User-Role")


def get_user_id():
    return request.headers.get("X-User-ID")


def require_auth():
    """ERR_UNAUTHENTICATED if X-User-Role missing or not a recognized role."""
    role = get_role()
    if not role or role not in ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or unknown X-User-Role.")
    return role


def require_role(allowed_roles):
    """Auth first, then authorization. Returns the validated role."""
    role = require_auth()
    if role not in allowed_roles:
        raise errors.err(
            errors.ERR_FORBIDDEN_ROLE,
            "Role %s is not permitted for this operation." % role,
        )
    return role


def require_owner(account_id):
    """When acting as Customer, X-User-ID must equal the owning account id.

    Operator roles bypass ownership. (PRD §2.1)
    """
    role = get_role()
    if role == "Customer":
        if get_user_id() != account_id:
            raise errors.err(
                errors.ERR_NOT_RESOURCE_OWNER,
                "Customer does not own this resource.",
            )
