"""Auth header extraction, role checking, and request parsing helpers.

Validation priority (PRD §2.9):
  1. user context — X-User-ID / X-User-Role present, role declared, and for
     entity-backed roles (ClientApprover -> ClientContact, OutsideCounsel ->
     CounselFirm) the X-User-ID resolves to an existing instance.
  2. role authorization — acting role is listed for the endpoint.
"""

from flask import request

import db as dbmod
from errors import (
    raise_err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_INVALID_REQUEST,
)

ROLES = {
    "PlatformAdmin",
    "DocketingClerk",
    "DocketingManager",
    "RecordsSpecialist",
    "FinanceOfficer",
    "ClientApprover",
    "OutsideCounsel",
}

ALL_ROLES = sorted(ROLES)

# Entity-backed roles: X-User-ID must reference an existing backing instance.
_ENTITY_BACKED_STORE = {
    "ClientApprover": "contacts",
    "OutsideCounsel": "counsel_firms",
}


def get_caller():
    """Priority 1: extract and validate the user context headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    backing = _ENTITY_BACKED_STORE.get(role)
    if backing is not None and user_id not in dbmod.DB[backing]:
        raise_err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            f"X-User-ID does not reference an existing instance for role {role}",
        )
    return user_id, role


def require_roles(allowed):
    """Priorities 1-2: user context, then role authorization."""
    user_id, role = get_caller()
    if role not in allowed:
        raise_err(ERR_FORBIDDEN_FOR_ROLE, f"Role {role} is not authorized for this endpoint")
    return user_id, role


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def parse_pagination():
    """limit/offset per SCAFFOLD §1.0 (default 10, min 1, max 100; offset 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def query_param(name):
    """Read a query parameter; falls back to a JSON body field for robustness."""
    v = request.args.get(name)
    if v is not None:
        return v
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        return body.get(name)
    return None
