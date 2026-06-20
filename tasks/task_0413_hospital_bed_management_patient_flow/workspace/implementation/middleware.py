"""Auth header extraction, RBAC enforcement, body/pagination parsing helpers."""

from flask import request

import errors
from errors import err

VALID_ROLES = {
    "FlowAdmin",
    "BedControlCoordinator",
    "ChargeNurse",
    "TransferCenterAgent",
    "CaseManager",
    "EvsTech",
}


def authenticate():
    """Validate X-User-ID + X-User-Role. Returns (user_id, role) or raises 401."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def authorize(role, allowed_roles):
    """Raise 403 unless role is in the allowed set."""
    if role not in allowed_roles:
        raise err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")


def get_json_body():
    """Return the parsed JSON body as a dict; tolerate empty/missing body."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def parse_pagination():
    """Parse and validate limit/offset query params. Raises ERR_INVALID_PAGINATION."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    offset = 0

    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_PAGINATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(errors.ERR_INVALID_PAGINATION, "limit must be between 1 and 100")

    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err(errors.ERR_INVALID_PAGINATION, "offset must be an integer")
        if offset < 0:
            raise err(errors.ERR_INVALID_PAGINATION, "offset must be >= 0")

    return limit, offset
