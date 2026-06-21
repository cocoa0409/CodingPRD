"""Auth header extraction, role checking, pagination, and body parsing.

Auth scheme (PRD 2.1):
  - Two mandatory headers: X-User-ID and X-User-Role.
  - X-User-Role must be one of: Recruiter, AccountManager, Client, Candidate.
  - Missing either header, or an unrecognized role -> 401
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
  - Recruiter / AccountManager are opaque operator identities (X-User-ID is
    never compared to an entity id).
  - Client / Candidate are entity-backed (X-User-ID is the acting entity's id).
"""

from flask import request

import db
import errors
from errors import ApiError

ROLES = {"Recruiter", "AccountManager", "Client", "Candidate"}


def get_user_context():
    """Return (user_id, role); raise 401 if missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            401,
            "Missing or invalid user context header.",
        )
    return user_id, role


def require_role(role, allowed):
    """RBAC role gate (priority 2). Raise 403 if the role is not permitted."""
    if role not in allowed:
        raise ApiError(errors.ERR_UNAUTHORIZED, 403, "Role not permitted for this operation.")


def get_json_body():
    """Parse JSON body; tolerate empty body as {}."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError(errors.ERR_VALIDATION, 422, "Request body must be a JSON object.")
    return body


def parse_pagination():
    """Return (limit, offset) per PRD 2.3.

    limit defaults to 10, min 1, max 100. offset defaults to 0.
    Out-of-range / non-integer values are ERR_VALIDATION (422).
    """
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise ApiError(errors.ERR_VALIDATION, 422, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError(errors.ERR_VALIDATION, 422, "limit out of range.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise ApiError(errors.ERR_VALIDATION, 422, "offset must be an integer.")
        if offset < 0:
            raise ApiError(errors.ERR_VALIDATION, 422, "offset must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ASC (PRD 2.3), then slice."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
