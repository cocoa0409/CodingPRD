"""Auth header extraction and role checking per SCAFFOLD validations + roles."""

from flask import request

from errors import err_missing_headers, err_unauthorized, err_invalid_request

ROLES = {
    "PlatformAdmin", "Customer", "SalesRep", "Assessor", "AssessmentReviewer",
    "FundingOfficer", "InstallCoordinator", "InventoryManager", "ClaimsAdjuster",
}


def get_auth():
    """Extract (user_id, role); raises ApiError if headers missing/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err_missing_headers()
    if role not in ROLES:
        raise err_missing_headers()
    return user_id, role


def require_role(*allowed):
    """Validate auth headers and role membership; returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err_unauthorized()
    return user_id, role


def get_json_body(required_fields=()):
    """Parse the JSON request body; validate required fields exist."""
    body = request.get_json(silent=True)
    if body is None:
        if required_fields:
            raise err_invalid_request("Request body must be JSON")
        return {}
    for f in required_fields:
        if f not in body or body[f] is None:
            raise err_invalid_request(f"Missing required field: {f}")
    return body


def get_pagination():
    """Parse limit/offset per response_envelope pagination defaults."""
    args = request.args
    limit_s = args.get("limit")
    offset_s = args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except ValueError:
            raise err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid_request("limit out of range")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except ValueError:
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset out of range")
    return limit, offset
