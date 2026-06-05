"""Auth header extraction and role checking (PRD §2.1, §2.7).

Auth headers (PRD §2.1):
  X-User-ID   — acting principal id
  X-User-Role — BillingAdmin | AccountOwner | Anonymous

A request whose X-User-Role is missing/malformed, or (for any role other than
Anonymous) whose X-User-ID is missing/malformed, -> ERR_UNAUTHENTICATED (401).
A well-authenticated request whose role is not permitted -> ERR_UNAUTHORIZED (403).
"""
from flask import request

import errors

VALID_ROLES = {"BillingAdmin", "AccountOwner", "Anonymous"}


def authenticate():
    """Returns (role, user_id). Raises ERR_UNAUTHENTICATED on malformed auth."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if role is None or role.strip() == "" or role not in VALID_ROLES:
        raise errors.unauthenticated("X-User-Role missing or malformed")

    if role != "Anonymous":
        if user_id is None or user_id.strip() == "":
            raise errors.unauthenticated("X-User-ID missing or malformed")

    return role, user_id


def require_role(role, allowed):
    """ERR_UNAUTHORIZED when the authenticated role is not in `allowed`."""
    if role not in allowed:
        raise errors.unauthorized(f"Role {role} is not permitted for this operation")


def require_account_owner_match(role, user_id, account_id):
    """AccountOwner may act only on their own account (PRD §2.1).

    X-User-ID equals the Account.id for AccountOwner. BillingAdmin is not
    constrained. (Anonymous never reaches owned resources.)
    """
    if role == "AccountOwner" and user_id != account_id:
        raise errors.unauthorized("AccountOwner may act only on their own account")
