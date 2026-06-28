"""Auth header extraction and role checking (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. Missing/malformed either
header -> ERR_MISSING_AUTH (401). Well-formed but role not permitted for the
endpoint -> ERR_FORBIDDEN_ROLE (403).
"""
from flask import request

from errors import err

VALID_ROLES = {"Underwriter", "PolicyAdmin", "ClaimsExaminer", "Policyholder"}


def get_identity():
    """Return (user_id, role), raising ERR_MISSING_AUTH if absent/malformed.

    A malformed header is one that is missing, empty, or carries a role value
    outside the four recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise err("ERR_MISSING_AUTH", "X-User-ID header missing or malformed")
    if not role or role not in VALID_ROLES:
        raise err("ERR_MISSING_AUTH", "X-User-Role header missing or malformed")
    return user_id, role


def require_roles(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE if role is not in the allowed set for the endpoint."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted for this operation" % role)


def require_owner_if_policyholder(role, user_id, policy):
    """On a Policyholder-scoped mutation, X-User-ID must equal
    Policy.policyholder_user_id (PRD §2.1); else ERR_NOT_POLICY_OWNER."""
    if role == "Policyholder" and user_id != policy.get("policyholder_user_id"):
        raise err("ERR_NOT_POLICY_OWNER", "Caller is not the policy owner")
