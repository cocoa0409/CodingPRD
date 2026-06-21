"""Auth header extraction and RBAC.

PRD §2.1: two mandatory headers — X-User-ID (acting account id / opaque id) and
X-User-Role (one of Anonymous, Buyer, Seller, PlatformAdmin).
"""
from flask import request

import db
import errors

VALID_ROLES = {"Anonymous", "Buyer", "Seller", "PlatformAdmin"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_auth():
    """Validate the two auth headers are present and well-formed.

    Returns a Caller. Raises ERR_UNAUTHENTICATED (priority 1) when a header is
    missing or malformed (PRD §2.1, §2.10).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.unauthenticated()
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise errors.unauthenticated()
    if role not in VALID_ROLES:
        raise errors.unauthenticated()
    return Caller(user_id, role)


def require_role(caller, allowed_roles):
    """ERR_FORBIDDEN_ROLE (priority 2) when the role is not permitted (PRD §2.1)."""
    if caller.role not in allowed_roles:
        raise errors.forbidden_role()


def check_account_not_closed(caller):
    """PRD §2.1/§3.1: a CLOSED account may not perform any mutation -> ERR_ACCOUNT_CLOSED.

    Only applies to entity-backed roles (Buyer/Seller) whose X-User-ID maps to an
    Account. Anonymous and PlatformAdmin identities are opaque and not tied to an
    account, so they are never "closed".
    """
    if caller.role in ("Buyer", "Seller"):
        acct = db.accounts.get(caller.user_id)
        if acct is not None and acct["status"] == "CLOSED":
            raise errors.account_closed()
