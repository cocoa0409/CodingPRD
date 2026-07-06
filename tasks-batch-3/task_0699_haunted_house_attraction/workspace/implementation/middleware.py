"""Auth header extraction, RBAC role checking, pagination, and body parsing.

Headers (PRD §2.1):
  X-User-ID    — identifies the acting principal
  X-User-Role  — declares the capacity (role) in which they act

Roles (spelled precisely): OpsManager, BoxOffice, Guest, Actor.
"""
from flask import request

import errors
from errors import ApiError

VALID_ROLES = {"OpsManager", "BoxOffice", "Guest", "Actor"}


def get_identity():
    """Extract and validate auth headers.

    A request missing either header is rejected with ERR_MISSING_AUTH (401).
    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError(errors.ERR_MISSING_AUTH, 401, "Missing X-User-ID or X-User-Role header.")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError(errors.ERR_MISSING_AUTH, 401, "Malformed X-User-ID header.")
    if not isinstance(role, str) or role.strip() == "":
        raise ApiError(errors.ERR_MISSING_AUTH, 401, "Malformed X-User-Role header.")
    if role not in VALID_ROLES:
        # An unrecognised role cannot be authorised for any operation.
        raise ApiError(errors.ERR_ROLE_FORBIDDEN, 403, "Unknown role.")
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_ROLE_FORBIDDEN (403) if the acting role is not in `allowed`."""
    if role not in allowed:
        raise ApiError(errors.ERR_ROLE_FORBIDDEN, 403, "Role is not permitted for this operation.")


def require_owner(role, user_id, owner_guest_id):
    """Ownership check (PRD §2.1, §2.11). When acting as Guest, X-User-ID must
    equal the owning guest_id of the targeted resource, else ERR_NOT_OWNER (403).
    OpsManager / BoxOffice / Actor are opaque identities and skip the check.
    """
    if role == "Guest" and user_id != owner_guest_id:
        raise ApiError(errors.ERR_NOT_OWNER, 403, "Acting guest does not own this resource.")


def parse_pagination():
    """Parse limit/offset from query params (PRD §2.3).

    limit defaults to 10, constrained 1..100.
    offset defaults to 0, may not be negative.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100.")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "offset must be an integer.")
        if offset < 0:
            raise ApiError(errors.ERR_INVALID_REQUEST, 400, "offset may not be negative.")

    return limit, offset


def get_json_body():
    """Return the request JSON body as a dict (empty dict if none/empty).

    A non-object or unparseable body is ERR_INVALID_REQUEST (400).
    """
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Request body must be valid JSON.")
    if not isinstance(body, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return body
