"""Authentication, RBAC and identity binding (PRD section 2.1)."""

from flask import request

import store
from errors import fail

ROLES = [
    "BoardClerk", "BoardPresident", "BoardMember", "PolicyAnalyst",
    "Superintendent", "SchoolPrincipal", "LegalUpdateService", "Public",
]

ALL_ROLES = list(ROLES)

READ_ROLES_PUBLIC = list(ROLES)
READ_ROLES_INTERNAL = [
    "BoardClerk", "BoardPresident", "BoardMember", "PolicyAnalyst", "Superintendent",
]
READ_ROLES_MANDATE = [
    "BoardClerk", "BoardPresident", "BoardMember", "PolicyAnalyst",
    "Superintendent", "LegalUpdateService",
]
READ_ROLES_EVAL = ["BoardClerk", "BoardPresident", "BoardMember", "Superintendent"]


def identity():
    """Validate the two auth headers and return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    role = role.strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    return str(user_id).strip(), role


def authorize(allowed_roles):
    """Priority 1 then priority 2 of the refusal ladder."""
    user_id, role = identity()
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE",
             "Role %s is not authorized for this operation." % role)
    return user_id, role


def acting_president(user_id):
    """A BoardPresident caller must be the SEATED trustee holding office PRESIDENT."""
    member = store.db["board_members"].get(user_id)
    if member is None or member.get("status") != "SEATED" \
            or member.get("office") != "PRESIDENT":
        fail("ERR_IDENTITY_MISMATCH",
             "The caller is not the seated board president.")
    return member


def enforce_president(user_id, role):
    if role == "BoardPresident":
        return acting_president(user_id)
    return None
