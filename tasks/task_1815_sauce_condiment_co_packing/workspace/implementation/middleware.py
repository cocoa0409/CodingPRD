"""Auth header extraction, role checking, and Customer ownership (PRD §2.1).

Headers: X-User-ID and X-User-Role on every request. Roles: OpsAdmin,
Customer, ProcessAuthority, QAReviewer. For Customer, X-User-ID is the id of
the acting CustomerAccount and is compared against the resource chain's
customer_id; for the other roles it is an opaque operator identifier.
"""
from flask import g, request

from errors import err, ERR_MISSING_OR_INVALID_USER_CONTEXT, ERR_FORBIDDEN

ROLES = {"OpsAdmin", "Customer", "ProcessAuthority", "QAReviewer"}


def authenticate():
    """Runs before every /copack request (validation stage 1)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT,
            400,
            "missing or unrecognized X-User-ID / X-User-Role",
        )
    g.user_id = uid
    g.user_role = role


def require_roles(*roles):
    """Validation stage 2: the presented role must be listed for the endpoint."""
    if g.user_role not in roles:
        raise err(ERR_FORBIDDEN, 403, "caller role is not listed for this endpoint")


def check_customer_scope(owner_customer_id):
    """Validation stage 3: a Customer caller may only act inside its own
    customer_id ownership chain."""
    if g.user_role == "Customer" and g.user_id != owner_customer_id:
        raise err(ERR_FORBIDDEN, 403, "resource is outside the caller's customer chain")
