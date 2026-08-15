"""Auth header extraction, role checking, entity-backed scoping."""

from flask import request

import errors

VALID_ROLES = {
    "DeskTrader",
    "BorrowerRep",
    "OwnerRep",
    "RiskOfficer",
    "OpsSettler",
    "DeskAdmin",
}

ENTITY_BACKED_ROLES = {"BorrowerRep", "OwnerRep"}


def get_auth():
    """Returns (user_id, role). Raises ApiError on missing/invalid role."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in VALID_ROLES:
        raise errors.make_error(errors.ERR_UNAUTHENTICATED, "X-User-Role header missing or not a declared role")
    user_id = request.headers.get("X-User-ID", "")
    return user_id, role


def require_roles(role, allowed_roles):
    """Raise ERR_FORBIDDEN if role not in allowed_roles."""
    if role not in allowed_roles:
        raise errors.make_error(errors.ERR_FORBIDDEN, "Role not permitted on this endpoint")


def check_entity_scope(role, user_id, owner_id=None, borrower_id=None):
    """For entity-backed roles, verify caller's X-User-ID matches the resource FK."""
    if role == "OwnerRep" and owner_id is not None:
        if user_id != owner_id:
            raise errors.make_error(errors.ERR_FORBIDDEN, "OwnerRep X-User-ID must equal resource owner_id")
    if role == "BorrowerRep" and borrower_id is not None:
        if user_id != borrower_id:
            raise errors.make_error(errors.ERR_FORBIDDEN, "BorrowerRep X-User-ID must equal resource borrower_id")


def check_list_scope(role, user_id, filter_args):
    """Auto-scope list queries for entity-backed roles.
    filter_args: dict of query params already extracted (may contain None).
    Returns modified filter dict."""
    if role == "OwnerRep" and "owner_id" in filter_args:
        if filter_args["owner_id"] is not None and filter_args["owner_id"] != user_id:
            raise errors.make_error(errors.ERR_FORBIDDEN, "OwnerRep must pass own id as owner_id filter")
        filter_args["owner_id"] = user_id
    if role == "BorrowerRep" and "borrower_id" in filter_args:
        if filter_args["borrower_id"] is not None and filter_args["borrower_id"] != user_id:
            raise errors.make_error(errors.ERR_FORBIDDEN, "BorrowerRep must pass own id as borrower_id filter")
        filter_args["borrower_id"] = user_id
    return filter_args
