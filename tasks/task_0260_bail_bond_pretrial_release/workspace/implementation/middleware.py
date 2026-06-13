"""Auth extraction, RBAC, body parsing, and pagination parsing.

Auth headers (PRD §2.1): X-User-ID and X-User-Role, both mandatory.
Roles: BondsAgent, Court, ComplianceOfficer, RecoveryAgent, SystemAdmin.
"""
from flask import request

from errors import err

VALID_ROLES = {"BondsAgent", "Court", "ComplianceOfficer", "RecoveryAgent", "SystemAdmin"}


def authenticate():
    """Validate the two auth headers are present and well-formed.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED (401) on absence/malformed.
    Note: a role string not in VALID_ROLES is malformed identity -> 401, not 403.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header.")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "Malformed X-User-ID header.")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Malformed X-User-Role header.")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN_ROLE (403) if role is not in the allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation." % role)


def get_json_body():
    """Parse the JSON body, tolerating an empty/absent body as {}.

    A present-but-malformed body raises ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def parse_pagination():
    """Parse limit/offset from the query string.

    Defaults: limit 10 (range [1,100]), offset 0 (>= 0).
    Out-of-range or non-integer -> ERR_VALIDATION (422).
    """
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION", "limit must be in [1, 100].")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_VALIDATION", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_VALIDATION", "offset must be >= 0.")

    return limit, offset
