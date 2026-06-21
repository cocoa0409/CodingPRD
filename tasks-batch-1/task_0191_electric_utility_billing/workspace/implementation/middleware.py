"""Auth header extraction and RBAC enforcement (PRD §2.1).

Every request carries two mandatory headers:
  X-User-ID    - acting principal id
  X-User-Role  - one of {BillingOperator, FieldDispatcher, AssistanceCaseworker,
                 Customer}

Three roles (BillingOperator, FieldDispatcher, AssistanceCaseworker) carry an
opaque identity that is never compared to any entity. The Customer role is
entity-backed: X-User-ID is the id of the acting Account, and ownership checks
compare a resource's account_id to that id.
"""
from flask import request

from errors import err

VALID_ROLES = {"BillingOperator", "FieldDispatcher", "AssistanceCaseworker", "Customer"}


def authenticate():
    """Validate X-User-ID and X-User-Role. Returns (user_id, role).

    Raises ERR_UNAUTHENTICATED (401) if either header is missing or if
    X-User-Role is not a recognized role (PRD §2.1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header.")
    if not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unknown X-User-Role header.")
    return user_id, role


def require_roles(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE (403) if role is not in the allowed set."""
    if role not in allowed:
        raise err(
            "ERR_FORBIDDEN_ROLE",
            "Role '%s' is not permitted for this operation." % role,
        )


def require_owner(role, user_id, owning_account_id):
    """Customer ownership check (PRD §2.1).

    A Customer's X-User-ID is the id of their Account; they may only act on
    resources whose account_id matches. Operator roles are opaque and never
    compared. A mismatch surfaces ERR_FORBIDDEN_ROLE (403) — a Customer acting
    outside their own account is not permitted under the role matrix.
    """
    if role == "Customer" and user_id != owning_account_id:
        raise err(
            "ERR_FORBIDDEN_ROLE",
            "Customer may only access their own account's resources.",
        )
