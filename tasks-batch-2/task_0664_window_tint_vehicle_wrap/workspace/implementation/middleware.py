"""Auth header extraction, RBAC role checking, and pagination parsing.

Headers (PRD §2.1):
  X-User-ID    — identifies the acting principal
  X-User-Role  — declares the capacity (role) in which they act

Roles: ShopManager, Installer, Customer, FleetManager, ComplianceOfficer
"""
from flask import request

import errors
from errors import ApiError

VALID_ROLES = {"ShopManager", "Installer", "Customer", "FleetManager", "ComplianceOfficer"}


def get_identity():
    """Extract and validate auth headers. Raises ERR_UNAUTHENTICATED (401) if
    either header is missing or malformed.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError(errors.ERR_UNAUTHENTICATED, 401, "Missing X-User-ID or X-User-Role header.")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError(errors.ERR_UNAUTHENTICATED, 401, "Malformed X-User-ID header.")
    if role not in VALID_ROLES:
        raise ApiError(errors.ERR_UNAUTHENTICATED, 401, "Malformed X-User-Role header.")
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE (403) if the acting role is not in `allowed`."""
    if role not in allowed:
        raise ApiError(errors.ERR_FORBIDDEN_ROLE, 403, "Role is not permitted for this operation.")


def parse_pagination():
    """Parse limit/offset from query params per PRD §2.3.

    limit defaults to 10, must be 1..100.
    offset defaults to 0, may not be negative.
    Out-of-bounds -> ERR_PAGINATION_INVALID (400).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_PAGINATION_INVALID, 400, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError(errors.ERR_PAGINATION_INVALID, 400, "limit must be between 1 and 100.")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_PAGINATION_INVALID, 400, "offset must be an integer.")
        if offset < 0:
            raise ApiError(errors.ERR_PAGINATION_INVALID, 400, "offset may not be negative.")

    return limit, offset


def get_json_body():
    """Return the request JSON body as a dict (empty dict if none/empty)."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return body
